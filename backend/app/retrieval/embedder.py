"""Embedding service: batches text through the configured embedding provider
(Ollama `nomic-embed-text` by default) and validates dimensionality against
the schema so a mis-configured model fails loudly instead of corrupting the index.
"""

from __future__ import annotations

from app.config import Settings, get_settings
from app.errors import ProviderError
from app.logging_config import get_logger
from app.providers import LLMProvider, get_embedding_provider

logger = get_logger(__name__)


class Embedder:
    def __init__(self, provider: LLMProvider | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.provider = provider or get_embedding_provider()
        self.dimensions = self.settings.embedding_dimensions

    @property
    def model_name(self) -> str:
        return getattr(self.provider, "embedding_model", self.provider.model)

    def embed_documents(self, texts: list[str], *, batch_size: int = 16) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            vectors.extend(self._embed_checked(batch))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed_checked([text])[0]

    def _embed_checked(self, texts: list[str]) -> list[list[float]]:
        vectors = self.provider.embed(texts)
        if len(vectors) != len(texts):
            raise ProviderError(
                "Embedding provider returned a different number of vectors than inputs.",
                details={"expected": len(texts), "received": len(vectors)},
            )
        for vector in vectors:
            if len(vector) != self.dimensions:
                raise ProviderError(
                    "Embedding dimensionality mismatch: the database column and the embedding model disagree.",
                    details={
                        "expected_dimensions": self.dimensions,
                        "model_dimensions": len(vector),
                        "embedding_model": self.model_name,
                        "fix": "Set EMBEDDING_DIMENSIONS to the model's size and re-run migrations + ingestion.",
                    },
                )
        return vectors

    def healthcheck(self) -> dict:
        return self.provider.healthcheck()
