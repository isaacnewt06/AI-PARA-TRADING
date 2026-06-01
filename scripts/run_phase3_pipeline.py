"""Run phase 3 operational strategy pipeline end-to-end."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.application.compile_setups import SetupCompilationApplicationService
from src.application.normalize_rules import RuleNormalizationApplicationService
from src.core.config import get_settings
from src.core.logging import setup_logging
from src.db.session import init_db, session_scope


def main() -> None:
    settings = get_settings()
    setup_logging(settings)
    init_db()
    with session_scope() as session:
        normalization = RuleNormalizationApplicationService(session).run()
        compilation = SetupCompilationApplicationService(session).run(score=True)
        print({"normalization": normalization, "compilation": compilation})


if __name__ == "__main__":
    main()
