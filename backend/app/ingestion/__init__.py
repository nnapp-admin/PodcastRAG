"""Transcript ingestion: discover -> clean -> metadata -> chunk -> embed -> pgvector."""

from app.ingestion.pipeline import IngestionSummary, ingest_path

__all__ = ["IngestionSummary", "ingest_path"]
