"""Audio processing and transcription interface."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import tempfile
from typing import Any

from sqlalchemy.orm import Session

from src.ai.interfaces import TranscriptionClient
from src.core.config import Settings
from src.core.logging import get_logger
from src.db.models.file_asset import FileAsset
from src.db.models.media import AudioAsset
from src.db.models.transcript import Transcript

logger = get_logger(__name__)


@dataclass(slots=True)
class TranscriptionResult:
    """Represents the result of a transcription execution."""

    status: str
    language: str | None
    text: str | None


class MockTranscriptionClient(TranscriptionClient):
    """Placeholder transcriber for phase 1.5 wiring."""

    def transcribe(self, audio_path: Path) -> TranscriptionResult:
        # TODO: replace this mock with OpenAI Whisper or another provider adapter in phase 1.5.
        return TranscriptionResult(
            status="pending_provider",
            language=None,
            text=f"TODO: connect real transcription provider for {audio_path.name}",
        )


class OpenAITranscriptionClient(TranscriptionClient):
    """OpenAI-backed audio transcription client."""

    MAX_AUDIO_BYTES = 24 * 1024 * 1024
    MAX_AUDIO_DURATION_SECONDS = 1_200

    def __init__(self, *, api_key: str, model: str, ffmpeg_path: str = "ffmpeg") -> None:
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key)
        self.ffmpeg_path = ffmpeg_path
        candidates = [model, "gpt-4o-transcribe", "whisper-1"]
        self.models = []
        for candidate in candidates:
            if candidate and candidate not in self.models:
                self.models.append(candidate)

    def transcribe(self, audio_path: Path) -> TranscriptionResult:
        chunk_dir: tempfile.TemporaryDirectory[str] | None = None
        chunk_paths = [audio_path]
        try:
            chunk_paths, chunk_dir = self._prepare_chunks(audio_path)
            if len(chunk_paths) == 1:
                return self._transcribe_single(chunk_paths[0])

            combined_text: list[str] = []
            language: str | None = None
            for chunk_path in chunk_paths:
                chunk_result = self._transcribe_single(chunk_path)
                if chunk_result.text:
                    combined_text.append(chunk_result.text.strip())
                if language is None and chunk_result.language:
                    language = chunk_result.language
            return TranscriptionResult(
                status="completed" if combined_text else "pending_provider",
                language=language,
                text="\n\n".join(part for part in combined_text if part),
            )
        finally:
            if chunk_dir is not None:
                chunk_dir.cleanup()

    def _transcribe_single(self, audio_path: Path) -> TranscriptionResult:
        last_exc: Exception | None = None
        for model in self.models:
            try:
                with audio_path.open("rb") as handle:
                    response: Any = self.client.audio.transcriptions.create(
                        model=model,
                        file=handle,
                    )
                text = getattr(response, "text", None) or (response.get("text") if isinstance(response, dict) else None)
                language = getattr(response, "language", None) or (
                    response.get("language") if isinstance(response, dict) else None
                )
                return TranscriptionResult(
                    status="completed" if text else "pending_provider",
                    language=language,
                    text=text,
                )
            except Exception as exc:
                last_exc = exc
                logger.warning("OpenAI transcription model %s unavailable for %s: %s", model, audio_path.name, exc)
        if last_exc is not None:
            raise last_exc
        return TranscriptionResult(status="pending_provider", language=None, text=None)

    def _prepare_chunks(self, audio_path: Path) -> tuple[list[Path], tempfile.TemporaryDirectory[str] | None]:
        file_size = audio_path.stat().st_size
        duration_seconds = self._probe_duration_seconds(audio_path)
        if file_size <= self.MAX_AUDIO_BYTES and (
            duration_seconds is None or duration_seconds <= self.MAX_AUDIO_DURATION_SECONDS
        ):
            return [audio_path], None

        chunk_dir = tempfile.TemporaryDirectory(prefix=f"{audio_path.stem}_chunks_")
        chunk_pattern = str(Path(chunk_dir.name) / "chunk_%03d.mp3")
        command = [
            self.ffmpeg_path,
            "-y",
            "-i",
            str(audio_path),
            "-f",
            "segment",
            "-segment_time",
            str(self.MAX_AUDIO_DURATION_SECONDS),
            "-reset_timestamps",
            "1",
            "-c",
            "copy",
            chunk_pattern,
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            chunk_dir.cleanup()
            raise RuntimeError(
                f"Failed to split audio for transcription: {audio_path.name}: {completed.stderr[:400]}"
            )
        chunk_paths = sorted(Path(chunk_dir.name).glob("chunk_*.mp3"))
        if not chunk_paths:
            chunk_dir.cleanup()
            raise RuntimeError(f"Audio split produced no chunks for {audio_path.name}")
        logger.info(
            "Split long audio %s into %s chunks for transcription", audio_path.name, len(chunk_paths)
        )
        return chunk_paths, chunk_dir

    def _probe_duration_seconds(self, audio_path: Path) -> float | None:
        ffprobe_path = self._resolve_ffprobe_path()
        command = [
            ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
        except FileNotFoundError:
            return None
        if completed.returncode != 0:
            return None
        try:
            return float((completed.stdout or "").strip())
        except ValueError:
            return None

    def _resolve_ffprobe_path(self) -> str:
        ffmpeg_path = self.ffmpeg_path
        lower_path = ffmpeg_path.lower()
        if lower_path.endswith("ffmpeg.exe"):
            return ffmpeg_path[:-10] + "ffprobe.exe"
        if lower_path.endswith("ffmpeg"):
            return ffmpeg_path[:-6] + "ffprobe"
        return "ffprobe"


def build_default_transcription_client(settings: Settings | None) -> TranscriptionClient:
    """Return the best available transcription client for the current environment."""

    if settings is not None and settings.openai_api_key:
        try:
            return OpenAITranscriptionClient(
                api_key=settings.openai_api_key,
                model=settings.openai_transcription_model,
                ffmpeg_path=settings.ffmpeg_path,
            )
        except Exception as exc:
            logger.warning("Falling back to mock transcription client: %s", exc)
    return MockTranscriptionClient()


def transcription_provider_name(client: TranscriptionClient, settings: Settings | None) -> str:
    """Resolve a human-readable provider name for stored transcript rows."""

    if isinstance(client, OpenAITranscriptionClient):
        return "openai"
    if settings is None:
        return "mock"
    return settings.tuning.transcript_provider


class AudioProcessor:
    """Persist audio metadata and placeholder transcripts."""

    def __init__(
        self,
        session: Session,
        settings: Settings,
        transcription_client: TranscriptionClient | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.transcription_client = transcription_client or build_default_transcription_client(settings)

    def process(self, file_asset: FileAsset) -> AudioAsset:
        audio_asset = file_asset.audio_asset or AudioAsset(file_id=file_asset.id, status="pending")
        transcript = file_asset.transcript or Transcript(source_file_id=file_asset.id)
        result = self.transcription_client.transcribe(Path(file_asset.stored_path))
        transcripts_dir = self.settings.paths.transcripts_dir / "audio"
        transcripts_dir.mkdir(parents=True, exist_ok=True)
        transcript_path = transcripts_dir / f"file_{file_asset.id}.txt"
        transcript_text = result.text or ""
        transcript_path.write_text(transcript_text, encoding="utf-8")
        transcript.provider = transcription_provider_name(self.transcription_client, self.settings)
        transcript.status = result.status
        transcript.language = result.language
        transcript.content = transcript_text
        transcript.content_path = str(transcript_path.resolve())
        file_asset.status = result.status
        audio_asset.status = result.status
        self.session.add(transcript)
        self.session.flush()
        audio_asset.transcript_id = transcript.id
        self.session.add(audio_asset)
        self.session.flush()
        logger.info("Prepared audio asset %s for transcription", file_asset.file_name)
        return audio_asset
