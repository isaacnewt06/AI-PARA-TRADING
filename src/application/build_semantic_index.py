"""Application service for semantic indexing."""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.core.config import Settings
from src.knowledge.vector_index import LocalVectorIndexService


class SemanticIndexApplicationService:
    """Build the local vector index for content chunks."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def run(self, rebuild: bool = False) -> dict:
        return LocalVectorIndexService(self.session, self.settings).build(rebuild=rebuild)
