from src.core.config import reload_settings


def test_reload_settings_applies_override(tmp_path) -> None:
    settings = reload_settings(
        {
            "DATA_DIR": str(tmp_path / "custom_data"),
            "DB_URL": "sqlite:///./relative.db",
        }
    )
    assert settings.resolved_data_dir == (tmp_path / "custom_data").resolve()
    assert settings.resolved_db_url.startswith("sqlite:///")
    assert "relative.db" in settings.resolved_db_url
