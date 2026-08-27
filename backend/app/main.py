import asyncio
from contextlib import asynccontextmanager
from contextlib import suppress

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.encoders import jsonable_encoder

from app.config import get_settings
from app.database import SessionLocal, engine
from app.routers import (
    audit,
    auth,
    chat,
    delivery,
    hermes,
    invitations,
    knowledge,
    knowledge_operations,
    experience,
    memory,
    organization,
    pipeline,
    portal,
    projects,
    reminders,
    skills,
    users,
    work_items,
)
from sqlalchemy import text
from app.services.work_item_archiver import run_work_item_archiver

settings = get_settings()

OPENAPI_TAGS = [
    {"name": "Authentication", "description": "JWT login, refresh, identity, and OAuth stubs."},
    {"name": "Users", "description": "Administrator-only user and role management."},
    {
        "name": "Hermes Profiles",
        "description": "One isolated Hermes profile per platform user; multiplexed in Phase 2.",
    },
    {
        "name": "Chat",
        "description": "Stateful sessions with a compatibility mock or private Hermes SSE adapter.",
    },
    {"name": "Knowledge Base", "description": "Organization-scoped entries, ingestion, retrieval, and citations."},
    {"name": "Skills", "description": "SKILL.md management and mock AI generation."},
    {"name": "Memory", "description": "Owner-scoped durable memory in PostgreSQL."},
    {"name": "Reminders", "description": "Reminder metadata; scheduling and delivery are stubs."},
]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    archive_task: asyncio.Task[None] | None = None
    if settings.work_item_archive_enabled:
        archive_task = asyncio.create_task(
            run_work_item_archiver(
                SessionLocal,
                poll_seconds=settings.work_item_archive_poll_seconds,
                batch_size=settings.work_item_archive_batch_size,
            ),
            name="work-item-archiver",
        )
    try:
        yield
    finally:
        if archive_task is not None:
            archive_task.cancel()
            with suppress(asyncio.CancelledError):
                await archive_task


def docs_urls(expose: bool) -> dict[str, str | None]:
    """Docs/OpenAPI exposure helper: the formal entry keeps both closed."""
    if expose:
        return {"docs_url": "/docs", "openapi_url": "/openapi.json"}
    return {"docs_url": None, "openapi_url": None}


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description=(
        "Hermes enterprise platform MVP API. Authentication is JWT Bearer. Chat preserves the "
        "stateful session contract; the default local provider is a compatibility mock and the "
        "pinned Hermes HTTP adapter is enabled only for a private deployment."
    ),
    openapi_tags=OPENAPI_TAGS,
    redoc_url=None,
    lifespan=lifespan,
    **docs_urls(settings.expose_docs),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    if exc.status_code == 413 and exc.detail == "payload_too_large":
        code = "payload_too_large"
        message = "Request payload exceeds the allowed size"
    elif exc.status_code == 422 and exc.detail == "content_type_not_allowed":
        code = "content_type_not_allowed"
        message = "Uploaded content type is not allowed"
    else:
        code = f"http_{exc.status_code}"
        message = str(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": code, "message": message}},
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": "Request validation failed",
                "details": jsonable_encoder(exc.errors()),
            }
        },
    )


@app.get("/health", tags=["System"], summary="Service health check")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "hermes-platform-backend"}


@app.get("/ready", tags=["System"], summary="Service readiness check")
async def ready() -> JSONResponse:
    components: dict[str, str] = {"database": "unknown", "rag_worker": "disabled"}
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        components["database"] = "ready"
    except Exception:
        components["database"] = "unavailable"

    if settings.rag_embedding_enabled:
        worker_url = settings.rag_query_embedding_url
        if not worker_url or not settings.rag_query_embedding_token:
            components["rag_worker"] = "misconfigured"
        else:
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    response = await client.get(f"{worker_url.rstrip('/')}/health")
                components["rag_worker"] = "ready" if response.is_success else "unavailable"
            except httpx.HTTPError:
                components["rag_worker"] = "unavailable"

    is_ready = all(
        (
            components["database"] == "ready",
            components["rag_worker"] in {"ready", "disabled"},
        )
    )
    payload = {
        "status": "ready" if is_ready else "not_ready",
        "database": components["database"],
        "rag_worker": components["rag_worker"],
        "components": components,
    }
    return JSONResponse(status_code=200 if is_ready else 503, content=payload)


for route in (
    auth.router,
    portal.enterprise_router,
    portal.dashboard_router,
    organization.router,
    users.router,
    invitations.router,
    hermes.router,
    chat.attachments_router,
    chat.router,
    knowledge.router,
    knowledge_operations.router,
    experience.router,
    audit.router,
    skills.router,
    memory.router,
    projects.router,
    reminders.router,
    pipeline.router,
    delivery.router,
    work_items.router,
):
    app.include_router(route)
