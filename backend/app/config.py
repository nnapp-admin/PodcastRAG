"""Application configuration.

Every runtime knob is an environment variable so the evaluator can switch
providers, models and retrieval parameters without touching code.
See `.env.example` at the repository root for the documented list.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["ollama", "anthropic", "openai"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App ---
    app_name: str = "Lenny Growth Assistant API"
    environment: str = Field(default="local", alias="ENVIRONMENT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    cors_origins: str = Field(default="http://localhost:8080,http://localhost:5173", alias="CORS_ORIGINS")

    # --- Database ---
    database_url: str = Field(
        default="postgresql+psycopg://lenny:lenny@localhost:5432/lenny",
        alias="DATABASE_URL",
    )

    # --- LLM provider selection ---
    llm_provider: ProviderName = Field(default="ollama", alias="LLM_PROVIDER")
    llm_model: str = Field(default="llama3.1:8b", alias="LLM_MODEL")
    llm_timeout_seconds: float = Field(default=180.0, alias="LLM_TIMEOUT_SECONDS")
    llm_max_output_tokens: int = Field(default=4096, alias="LLM_MAX_OUTPUT_TOKENS")
    llm_temperature: float = Field(default=0.2, alias="LLM_TEMPERATURE")

    # --- Ollama ---
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    ollama_embedding_model: str = Field(default="nomic-embed-text", alias="OLLAMA_EMBEDDING_MODEL")

    # --- Cloud providers (optional) ---
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    anthropic_base_url: str = Field(default="https://api.anthropic.com", alias="ANTHROPIC_BASE_URL")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")

    # --- Agent runtime ---
    # "auto"  -> Claude Agent SDK when provider == anthropic, local adapter otherwise
    # "claude_sdk" -> always use the Anthropic Claude Agent SDK runtime
    # "local" -> always use the local tool-loop adapter (same tools/prompts)
    agent_runtime: Literal["auto", "claude_sdk", "local"] = Field(default="auto", alias="AGENT_RUNTIME")
    agent_max_tool_steps: int = Field(default=6, alias="AGENT_MAX_TOOL_STEPS")

    # --- Embeddings ---
    embedding_provider: Literal["ollama"] = Field(default="ollama", alias="EMBEDDING_PROVIDER")
    embedding_dimensions: int = Field(default=768, alias="EMBEDDING_DIMENSIONS")

    # --- Retrieval ---
    retrieval_top_k: int = Field(default=6, alias="RETRIEVAL_TOP_K")
    retrieval_candidate_multiplier: int = Field(default=4, alias="RETRIEVAL_CANDIDATE_MULTIPLIER")
    retrieval_score_threshold: float = Field(default=0.35, alias="RETRIEVAL_SCORE_THRESHOLD")
    retrieval_min_chunks_for_answer: int = Field(default=1, alias="RETRIEVAL_MIN_CHUNKS_FOR_ANSWER")
    retrieval_reranker: Literal["none", "lexical"] = Field(default="lexical", alias="RETRIEVAL_RERANKER")

    # --- Ingestion ---
    transcripts_path: str = Field(default="./data/transcripts", alias="TRANSCRIPTS_PATH")
    chunk_target_chars: int = Field(default=1400, alias="CHUNK_TARGET_CHARS")
    chunk_overlap_chars: int = Field(default=200, alias="CHUNK_OVERLAP_CHARS")

    # --- Artifacts ---
    artifact_max_bytes: int = Field(default=200_000, alias="ARTIFACT_MAX_BYTES")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
