"""Video processing pipeline with FFmpeg hooks."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from src.core.config import Settings
from src.core.logging import get_logger
from src.db.models.file_asset import FileAsset
from src.db.models.media import VideoAsset
from src.db.models.transcript import Transcript
from src.processing.audio_processor import build_default_transcription_client, transcription_provider_name

logger = get_logger(__name__)


class VideoProcessor:
    """Extract audio from video while keeping the interface provider-agnostic."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.transcription_client = build_default_transcription_client(settings)

    def process(self, file_asset: FileAsset) -> VideoAsset:
        video_asset = file_asset.video_asset or VideoAsset(file_id=file_asset.id, status="pending")
        audio_dir = self.settings.paths.transcripts_dir / "audio_extracts"
        audio_dir.mkdir(parents=True, exist_ok=True)
        audio_path = audio_dir / f"{Path(file_asset.stored_path).stem}.mp3"

        try:
            # TODO: enrich with ffprobe metadata and hand off extracted audio to the transcription pipeline.
            command = [
                self.settings.ffmpeg_path,
                "-y",
                "-i",
                file_asset.stored_path,
                "-vn",
                "-acodec",
                "mp3",
                str(audio_path),
            ]
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
            if completed.returncode == 0:
                video_asset.audio_extract_path = str(audio_path.resolve())
                video_asset.status = "audio_extracted"
                transcript = file_asset.transcript or Transcript(source_file_id=file_asset.id)
                result: Any = self.transcription_client.transcribe(audio_path)
                transcript.provider = transcription_provider_name(self.transcription_client, self.settings)
                transcript.status = result.status
                transcript.language = result.language
                transcript_path = self.settings.paths.transcripts_dir / f"video_{file_asset.id}.txt"
                transcript_text = result.text or f"TODO: transcribe extracted audio for {file_asset.file_name}"
                transcript_path.write_text(transcript_text, encoding="utf-8")
                transcript.content_path = str(transcript_path.resolve())
                transcript.content = transcript_text
                self.session.add(transcript)
                self.session.flush()
                video_asset.transcript_id = transcript.id
                file_asset.status = "audio_extracted" if result.status == "pending_provider" else result.status
            else:
                video_asset.status = "ffmpeg_missing_or_failed"
                file_asset.status = "ffmpeg_missing_or_failed"
                logger.warning("FFmpeg extraction failed for %s: %s", file_asset.file_name, completed.stderr[:400])
        except FileNotFoundError:
            video_asset.status = "ffmpeg_not_found"
            file_asset.status = "ffmpeg_not_found"
            logger.warning("FFmpeg binary not found while processing %s", file_asset.file_name)

        self.session.add(video_asset)
        self.session.flush()
        return video_asset
