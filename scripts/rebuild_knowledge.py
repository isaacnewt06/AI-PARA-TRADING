"""Rebuild the knowledge base without reprocessing raw files."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.application.build_knowledge_base import KnowledgeBuildApplicationService
from src.core.config import get_settings
from src.core.logging import setup_logging
from src.db.session import init_db, session_scope


def main() -> None:
    settings = get_settings()
    setup_logging(settings)
    init_db()
    with session_scope() as session:
        summary = KnowledgeBuildApplicationService(session, settings).run()
        print(summary)


if __name__ == "__main__":
    main()
