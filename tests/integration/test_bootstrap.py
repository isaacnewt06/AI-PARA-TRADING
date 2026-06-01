from src.core.config import reload_settings
from src.db.session import get_engine
from src.db.session import init_db


def test_init_db(tmp_path) -> None:
    settings = reload_settings(
        {
            "DATA_DIR": str(tmp_path / "data"),
            "DB_URL": f"sqlite:///{(tmp_path / 'data' / 'test.db').as_posix()}",
        }
    )
    init_db()
    assert settings.resolved_data_dir == (tmp_path / "data").resolve()
    assert "test.db" in str(get_engine().url)
