"""Application service for strategy playbook generation."""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.knowledge.playbook_builder import PlaybookBuilder


class PlaybookGenerationApplicationService:
    """Generate strategy playbooks from extracted rules."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def run(self) -> dict:
        playbooks_created = PlaybookBuilder(self.session).build()
        return {"playbooks_created": playbooks_created}
