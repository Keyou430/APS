import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_agent_platform.db"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-with-sufficient-length"
os.environ["RAG_QUERY_AUDIT_HMAC_KEY"] = "test-only-query-audit-key"
os.environ["SINGLE_USER_MODE"] = "false"
os.environ["HERMES_USE_HTTP"] = "false"

import pytest_asyncio
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import (
    AuditEvent,
    MemoryCaptureSource,
    MemoryEmbeddingJob,
    MemoryExtractionJob,
    Project,
    ProjectMember,
    ProjectResourceLink,
    Skill,
    SkillAccessGrant,
    SkillVersion,
    MemoryRecord,
    MemoryRetrievalEvent,
    MemorySourceLink,
    MemoryVersion,
    DashboardDecision,
    DecisionAction,
    NotificationOutbox,
    PipelineOutput,
    PipelineRun,
    PipelineTask,
)
from app.seed import seed_database


@pytest.fixture(autouse=True)
def stub_hermes_cron_registration():
    register = AsyncMock(return_value="test-hermes-cron-job")
    with (
        patch("app.routers.pipeline.register_hermes_cron", new=register),
        patch(
            "app.main.reconcile_unbound_pipeline_tasks",
            new=AsyncMock(return_value=0),
        ),
    ):
        yield register


@pytest_asyncio.fixture(scope="session", loop_scope="session", autouse=True)
async def database():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    async with SessionLocal() as session:
        await seed_database(session)
    yield
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    Path("test_agent_platform.db").unlink(missing_ok=True)


@pytest_asyncio.fixture(autouse=True)
async def reset_memory_ledger():
    async with SessionLocal() as session:
        for model in (
            MemoryRetrievalEvent,
            MemoryExtractionJob,
            MemorySourceLink,
            MemoryVersion,
            MemoryEmbeddingJob,
            MemoryRecord,
            MemoryCaptureSource,
        ):
            await session.execute(delete(model))
        await session.execute(delete(AuditEvent).where(AuditEvent.resource_type == "memory"))
        for project_model in (ProjectResourceLink, ProjectMember, Project):
            await session.execute(delete(project_model))
        for skill_model in (SkillAccessGrant, SkillVersion, Skill):
            await session.execute(delete(skill_model))
        for pipeline_model in (
            DecisionAction,
            DashboardDecision,
            PipelineOutput,
            PipelineRun,
            NotificationOutbox,
            PipelineTask,
        ):
            await session.execute(delete(pipeline_model))
        await session.commit()
    yield


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


@pytest_asyncio.fixture
async def admin_headers(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin123"}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
