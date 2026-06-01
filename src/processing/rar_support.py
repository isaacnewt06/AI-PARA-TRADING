"""RAR backend detection and configuration for Windows-friendly archive inspection."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from src.core.config import Settings, get_settings
from src.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class RarBackendInfo:
    """Resolved RAR/7z backend used by rarfile."""

    available: bool
    backend_type: str | None = None
    backend_path: str | None = None
    source: str | None = None
    message: str | None = None


COMMON_BACKEND_CANDIDATES: tuple[tuple[str, list[str], list[str]], ...] = (
    ("unrar", ["unrar", "UnRAR.exe"], [r"C:\Program Files\WinRAR\UnRAR.exe"]),
    ("rar", ["rar", "rar.exe"], [r"C:\Program Files\WinRAR\rar.exe"]),
    ("sevenzip", ["7z", "7z.exe"], [r"C:\Program Files\7-Zip\7z.exe"]),
    ("sevenzip2", ["7zz", "7zz.exe"], []),
    ("bsdtar", ["bsdtar", "bsdtar.exe"], [r"C:\Program Files\Git\usr\bin\bsdtar.exe"]),
    ("bsdtar", ["tar", "tar.exe"], [r"C:\Windows\System32\tar.exe"]),
    ("unar", ["unar"], []),
)


def detect_rar_backend(settings: Settings | None = None, refresh: bool = False) -> RarBackendInfo:
    """Detect and configure a working backend for rarfile."""

    settings = settings or get_settings()
    if not settings.archive_inspection_enabled and not settings.tuning.archive_inspection_enabled:
        return RarBackendInfo(
            available=False,
            message="Archive inspection disabled by configuration.",
        )

    try:
        import rarfile
    except ImportError:
        return RarBackendInfo(available=False, message="Python package 'rarfile' is not installed.")

    configured_path = settings.rar_backend_path
    configured_type = (settings.rar_backend_type or "").strip().lower() or None
    candidates: list[tuple[str, str, str]] = []

    if configured_path:
        inferred = configured_type or _infer_backend_type(configured_path)
        candidates.append((inferred or "unknown", configured_path, "config"))

    for backend_type, names, paths in COMMON_BACKEND_CANDIDATES:
        for name in names:
            resolved = shutil.which(name)
            if resolved:
                candidates.append((backend_type, resolved, "path"))
        for path in paths:
            if Path(path).exists():
                candidates.append((backend_type, path, "common_path"))

    seen: set[tuple[str, str]] = set()
    for backend_type, backend_path, source in candidates:
        key = (backend_type, str(Path(backend_path)))
        if key in seen:
            continue
        seen.add(key)
        info = _configure_and_validate(backend_type, backend_path, source, refresh=refresh)
        if info.available:
            logger.info("RAR backend detected: type=%s path=%s source=%s", info.backend_type, info.backend_path, info.source)
            return info

    return RarBackendInfo(
        available=False,
        message=(
            "No working RAR backend detected. Expected one of: UnRAR.exe, rar.exe, 7z.exe, 7zz.exe, bsdtar, tar.exe."
        ),
    )


def _configure_and_validate(backend_type: str, backend_path: str, source: str, refresh: bool = False) -> RarBackendInfo:
    try:
        import rarfile
    except ImportError:
        return RarBackendInfo(available=False, message="rarfile not installed.")

    backend_type = backend_type.lower()
    path = str(Path(backend_path))

    try:
        if backend_type in {"unrar", "rar"}:
            rarfile.UNRAR_TOOL = path
            rarfile.tool_setup(unrar=True, unar=False, bsdtar=False, sevenzip=False, sevenzip2=False, force=True or refresh)
        elif backend_type == "unar":
            rarfile.UNAR_TOOL = path
            rarfile.tool_setup(unrar=False, unar=True, bsdtar=False, sevenzip=False, sevenzip2=False, force=True or refresh)
        elif backend_type == "bsdtar":
            rarfile.BSDTAR_TOOL = path
            rarfile.tool_setup(unrar=False, unar=False, bsdtar=True, sevenzip=False, sevenzip2=False, force=True or refresh)
        elif backend_type == "sevenzip":
            rarfile.SEVENZIP_TOOL = path
            rarfile.tool_setup(unrar=False, unar=False, bsdtar=False, sevenzip=True, sevenzip2=False, force=True or refresh)
        elif backend_type == "sevenzip2":
            rarfile.SEVENZIP2_TOOL = path
            rarfile.tool_setup(unrar=False, unar=False, bsdtar=False, sevenzip=False, sevenzip2=True, force=True or refresh)
        else:
            return RarBackendInfo(available=False, message=f"Unsupported backend type '{backend_type}'.")
    except Exception as exc:
        return RarBackendInfo(
            available=False,
            backend_type=backend_type,
            backend_path=path,
            source=source,
            message=f"Backend check failed: {exc}",
        )

    if not _backend_version_ok(path):
        return RarBackendInfo(
            available=False,
            backend_type=backend_type,
            backend_path=path,
            source=source,
            message="Backend executable was found but did not respond correctly.",
        )

    return RarBackendInfo(
        available=True,
        backend_type=backend_type,
        backend_path=path,
        source=source,
        message="RAR backend configured successfully.",
    )


def _backend_version_ok(path: str) -> bool:
    commands = [[path, "--version"], [path, "-version"], [path, "-?"], [path, "i"]]
    for command in commands:
        try:
            subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=8,
                check=False,
            )
            return True
        except Exception:
            continue
    return False


def _infer_backend_type(path: str) -> str | None:
    lowered = Path(path).name.lower()
    if lowered in {"unrar", "unrar.exe"}:
        return "unrar"
    if lowered in {"rar", "rar.exe"}:
        return "rar"
    if lowered in {"7z", "7z.exe"}:
        return "sevenzip"
    if lowered in {"7zz", "7zz.exe"}:
        return "sevenzip2"
    if lowered in {"bsdtar", "bsdtar.exe", "tar", "tar.exe"}:
        return "bsdtar"
    if lowered == "unar":
        return "unar"
    return None
