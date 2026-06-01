"""Database engine and session factory."""

from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from src.core.config import get_settings
from src.db.base import Base
from src.db.schema import ensure_schema_compatibility


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Build the SQLAlchemy engine."""
    settings = get_settings()
    db_url = settings.resolved_db_url
    connect_args: dict = {}
    if db_url.startswith("sqlite:///"):
        database_path = Path(db_url.replace("sqlite:///", "", 1))
        database_path.parent.mkdir(parents=True, exist_ok=True)
        connect_args = {
            "check_same_thread": False,
            "timeout": settings.tuning.sqlite_busy_timeout_seconds,
        }
    engine = create_engine(db_url, future=True, connect_args=connect_args)
    if db_url.startswith("sqlite:///"):
        _configure_sqlite(engine)
    return engine


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """Return the cached sessionmaker."""
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, expire_on_commit=False)


def init_db() -> None:
    """Create all tables."""
    from src.db.models import all_models  # noqa: F401

    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    ensure_schema_compatibility(engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional session scope."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _configure_sqlite(engine: Engine) -> None:
    """Apply SQLite pragmas suitable for local ingestion workloads."""

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()
