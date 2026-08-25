"""FastAPI application factory.

Cross-cutting concerns live here: structured request logging with a request id,
CORS for the frontend, and the single error envelope for every failure mode.
"""

from __future__ import annotations

import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import artifacts, chat, health, retrieval, sessions
from app.config import get_settings
from app.errors import AppError, error_envelope
from app.logging_config import configure_logging, get_logger, request_id_var, session_id_var

logger = get_logger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version=health.VERSION,
        description="Grounded product & growth assistant over Lenny's Podcast transcripts.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request_id_var.set(request_id)
        session_id_var.set(None)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "request_failed",
                extra={"path": request.url.path, "method": request.method},
            )
            raise
        duration_ms = (time.perf_counter() - started) * 1000
        response.headers["x-request-id"] = request_id
        if request.url.path != "/health":
            logger.info(
                "request_complete",
                extra={
                    "path": request.url.path,
                    "method": request.method,
                    "status": response.status_code,
                    "duration_ms": round(duration_ms, 1),
                },
            )
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        logger.warning(
            "app_error",
            extra={"code": exc.code, "status": exc.status_code, "details": exc.details},
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=error_envelope(exc.code, exc.message, exc.details, request_id_var.get()),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=error_envelope(
                "validation_failed",
                "Request payload is invalid.",
                {"errors": [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]},
                request_id_var.get(),
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {404: "not_found", 405: "method_not_allowed", 401: "unauthorized", 403: "forbidden"}
        return JSONResponse(
            status_code=exc.status_code,
            content=error_envelope(
                codes.get(exc.status_code, "http_error"),
                str(exc.detail),
                {},
                request_id_var.get(),
            ),
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled_error", extra={"error_type": type(exc).__name__})
        return JSONResponse(
            status_code=500,
            content=error_envelope(
                "internal_error",
                "Unexpected server error.",
                {"error_type": type(exc).__name__},
                request_id_var.get(),
            ),
        )

    app.include_router(health.router)
    app.include_router(sessions.router)
    app.include_router(chat.router)
    app.include_router(retrieval.router)
    app.include_router(artifacts.router)
    return app


app = create_app()
