"""Run the phase 2 semantic pipeline end-to-end."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.application.build_semantic_index import SemanticIndexApplicationService
from src.application.extract_trading_rules import TradingRuleExtractionApplicationService
from src.application.generate_playbooks import PlaybookGenerationApplicationService
from src.application.summarize_courses import CourseSummaryApplicationService
from src.core.config import get_settings
from src.core.logging import setup_logging
from src.db.session import init_db, session_scope


def main() -> None:
    settings = get_settings()
    setup_logging(settings)
    init_db()
    with session_scope() as session:
        semantic = SemanticIndexApplicationService(session, settings).run(rebuild=False)
        rules = TradingRuleExtractionApplicationService(session).run()
        playbooks = PlaybookGenerationApplicationService(session).run()
        course_summaries = CourseSummaryApplicationService(session).build()
        print(
            {
                "semantic": semantic,
                "rules": rules,
                "playbooks": playbooks,
                "course_summaries": course_summaries,
            }
        )


if __name__ == "__main__":
    main()
