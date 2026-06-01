"""Local vector indexing for content chunks."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.core.config import Settings
from src.core.logging import get_logger
from src.db.models.knowledge import ContentChunk
from src.db.repositories.knowledge import ChunkEmbeddingRepository, ContentChunkRepository
from src.knowledge.embeddings import LocalHashEmbeddingClient

logger = get_logger(__name__)


class LocalVectorIndexService:
    """Build and persist local embeddings for content chunks."""

    def __init__(self, session: Session, settings: Settings, embedding_client: LocalHashEmbeddingClient | None = None) -> None:
        self.session = session
        self.settings = settings
        self.embedding_client = embedding_client or LocalHashEmbeddingClient(
            dimension=getattr(settings.tuning, "embedding_dimension", 256)
        )
        self.chunk_repository = ContentChunkRepository(session)
        self.embedding_repository = ChunkEmbeddingRepository(session)

    def build(self, rebuild: bool = False) -> dict[str, int | str]:
        chunks = self.chunk_repository.list_quality_eligible() if rebuild else self.chunk_repository.list_pending_embeddings(
            self.embedding_client.provider_name
        )
        if not chunks:
            manifest = self._write_manifest(indexed_count=0)
            return {"indexed_chunks": 0, "provider": self.embedding_client.provider_name, "manifest": manifest}

        vectors = self.embedding_client.embed([chunk.clean_text for chunk in chunks])
        indexed_count = 0
        for chunk, vector in zip(chunks, vectors):
            self.embedding_repository.upsert(
                chunk_id=chunk.id,
                provider=self.embedding_client.provider_name,
                dimension=self.embedding_client.dimension,
                vector_json=json.dumps(vector, separators=(",", ":")),
                vector_norm=1.0 if any(vector) else 0.0,
            )
            chunk.embedding_provider = self.embedding_client.provider_name
            chunk.embedding_status = "indexed"
            self.session.add(chunk)
            indexed_count += 1
        self.session.flush()
        manifest = self._write_manifest(indexed_count=indexed_count)
        logger.info("Indexed %s content chunks with %s", indexed_count, self.embedding_client.provider_name)
        return {"indexed_chunks": indexed_count, "provider": self.embedding_client.provider_name, "manifest": manifest}

    def _write_manifest(self, indexed_count: int) -> str:
        manifest_path = self.settings.paths.vector_store_dir / "chunk_index_manifest.json"
        content = {
            "provider": self.embedding_client.provider_name,
            "dimension": self.embedding_client.dimension,
            "indexed_count": indexed_count,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        manifest_path.write_text(json.dumps(content, indent=2), encoding="utf-8")
        return str(manifest_path.resolve())
