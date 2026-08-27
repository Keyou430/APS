from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import KnowledgeIngestionJob, KnowledgeRetrievalEvent


pytestmark = pytest.mark.asyncio


async def test_rest_retrieval_writes_hmac_event_without_query_body(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    query = "sensitive operations query"
    response = await client.post(
        "/api/knowledge/retrieve",
        headers=admin_headers,
        json={"query": query, "source_ids": []},
    )
    assert response.status_code == 200, response.text
    async with SessionLocal() as db:
        event = await db.scalar(
            select(KnowledgeRetrievalEvent).order_by(KnowledgeRetrievalEvent.id.desc())
        )
    assert event is not None
    assert event.request_kind == "rest"
    assert event.chat_session_id is None
    assert event.query_hmac is not None and len(event.query_hmac) == 64
    assert event.query_hmac_version == 1
    assert event.query_sha256 is None
    assert query not in repr(event.__dict__)


async def test_operations_and_audit_endpoints_are_organization_scoped(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    overview = await client.get("/api/knowledge/operations/overview", headers=admin_headers)
    jobs = await client.get("/api/knowledge/operations/jobs", headers=admin_headers)
    audits = await client.get("/api/audit-events", headers=admin_headers)
    assert overview.status_code == 200, overview.text
    assert jobs.status_code == 200, jobs.text
    assert audits.status_code == 200, audits.text
    assert "content" not in overview.text
    assert "content_sha256" not in jobs.text
    assert "password_hash" not in audits.text


async def test_knowledge_entry_enabled_state_is_persisted_and_returned(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    created = await client.post(
        "/api/knowledge",
        headers=admin_headers,
        json={"type": "workflow_result", "title": "Toggle me", "content": "body"},
    )
    assert created.status_code == 201, created.text
    entry_id = created.json()["id"]
    assert created.json()["enabled"] is True

    disabled = await client.put(
        f"/api/knowledge/{entry_id}",
        headers=admin_headers,
        json={"enabled": False},
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["enabled"] is False

    listed = await client.get("/api/knowledge", headers=admin_headers)
    assert listed.status_code == 200, listed.text
    listed_item = next(item for item in listed.json()["items"] if item["id"] == entry_id)
    assert listed_item["enabled"] is False

    reenabled = await client.put(
        f"/api/knowledge/{entry_id}",
        headers=admin_headers,
        json={"enabled": True},
    )
    assert reenabled.status_code == 200, reenabled.text
    assert reenabled.json()["enabled"] is True


async def test_govern_retry_and_cancel_use_stable_status_transitions(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    entry = await client.post(
        "/api/knowledge",
        headers=admin_headers,
        json={"type": "workflow_result", "title": "Operations", "content": "body"},
    )
    async with SessionLocal() as db:
        failed = KnowledgeIngestionJob(
            organization_id=1, user_id=1, knowledge_entry_id=entry.json()["id"],
            content_sha256="1" * 64, status="failed", attempts=3,
            parser_version="test", embedding_model="text-embedding-v4",
            embedding_dimension=1024, last_error_code="embedding_unavailable",
        )
        processing = KnowledgeIngestionJob(
            organization_id=1, user_id=1, knowledge_entry_id=entry.json()["id"],
            content_sha256="2" * 64, status="processing", attempts=1,
            parser_version="test", embedding_model="text-embedding-v4",
            embedding_dimension=1024,
        )
        db.add_all([failed, processing])
        await db.commit()
        await db.refresh(failed)
        await db.refresh(processing)
        failed_id, processing_id = failed.id, processing.id

    retried = await client.post(
        f"/api/knowledge/operations/jobs/{failed_id}/retry", headers=admin_headers
    )
    cancelled = await client.post(
        f"/api/knowledge/operations/jobs/{processing_id}/cancel", headers=admin_headers
    )
    assert retried.status_code == 200 and retried.json()["status"] == "queued"
    assert retried.json()["attempts"] == 0
    assert retried.json()["error_code"] is None
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancel_requested"
