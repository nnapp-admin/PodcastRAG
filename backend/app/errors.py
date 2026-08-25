"""Application error taxonomy and the single structured error envelope.

Every failure surfaced by the API looks like:

    {"error": {"code": "...", "message": "...", "details": {...}, "request_id": "..."}}
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for errors that map to a documented HTTP status."""

    code = "internal_error"
    status_code = 500
    message = "Unexpected server error."

    def __init__(self, message: str | None = None, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message
        self.details = details or {}


class NotFoundError(AppError):
    code = "not_found"
    status_code = 404
    message = "Resource not found."


class ValidationFailedError(AppError):
    code = "validation_failed"
    status_code = 422
    message = "Request payload is invalid."


class DatabaseUnavailableError(AppError):
    code = "database_unavailable"
    status_code = 503
    message = "The database is unavailable. Check DATABASE_URL and that PostgreSQL is running."


class KnowledgeBaseEmptyError(AppError):
    code = "knowledge_base_empty"
    status_code = 409
    message = (
        "No transcripts have been ingested yet. Run the ingestion CLI "
        "(python -m app.ingestion.cli --path ./data/transcripts) before asking questions."
    )


# --- Provider errors -------------------------------------------------------


class ProviderError(AppError):
    code = "provider_error"
    status_code = 502
    message = "The selected model provider failed."


class ProviderUnavailableError(ProviderError):
    code = "provider_unavailable"
    status_code = 503
    message = (
        "The selected model provider is unreachable. If you are using Ollama, "
        "start it with `ollama serve` and confirm OLLAMA_BASE_URL."
    )


class ProviderAuthError(ProviderError):
    code = "provider_auth_error"
    status_code = 424
    message = "The selected model provider is missing or rejected its API key."


class ProviderTimeoutError(ProviderError):
    code = "provider_timeout"
    status_code = 504
    message = "The model provider timed out. Increase LLM_TIMEOUT_SECONDS or pick a smaller model."


class ProviderModelMissingError(ProviderError):
    code = "provider_model_missing"
    status_code = 424
    message = "The configured model is not available on the provider. Pull or configure the model first."


# --- Artifact errors -------------------------------------------------------


class ArtifactInvalidError(AppError):
    code = "artifact_invalid"
    status_code = 422
    message = "The generated artifact was rejected by the artifact validator."


def error_envelope(code: str, message: str, details: dict[str, Any], request_id: str | None) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": request_id,
        }
    }
