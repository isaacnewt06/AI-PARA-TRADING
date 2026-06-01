"""Initialize folders and the database."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.config import get_settings
from src.core.logging import setup_logging
from src.db.session import init_db


def main() -> None:
    settings = get_settings()
    setup_logging(settings)
    settings.paths.ensure()
    init_db()
    print("Bootstrap completed.")


if __name__ == "__main__":
    main()
