from pathlib import Path

from src.core.config import reload_settings
from src.processing.rar_support import detect_rar_backend


def test_detect_rar_backend_from_config(monkeypatch, tmp_path) -> None:
    backend_path = tmp_path / "7z.exe"
    backend_path.write_text("fake", encoding="utf-8")
    settings = reload_settings(
        {
            "RAR_BACKEND_PATH": str(backend_path),
            "RAR_BACKEND_TYPE": "sevenzip",
        }
    )

    monkeypatch.setattr("src.processing.rar_support._backend_version_ok", lambda path: True)
    monkeypatch.setattr(
        "rarfile.tool_setup",
        lambda **kwargs: object(),
    )

    info = detect_rar_backend(settings, refresh=True)

    assert info.available is True
    assert info.backend_type == "sevenzip"
    assert Path(info.backend_path) == backend_path


def test_detect_rar_backend_missing(monkeypatch) -> None:
    settings = reload_settings(
        {
            "RAR_BACKEND_PATH": "",
            "RAR_BACKEND_TYPE": "",
        }
    )
    monkeypatch.setattr("src.processing.rar_support.shutil.which", lambda name: None)
    monkeypatch.setattr("src.processing.rar_support.Path.exists", lambda self: False)

    info = detect_rar_backend(settings, refresh=True)

    assert info.available is False
    assert "No working RAR backend detected" in (info.message or "")
