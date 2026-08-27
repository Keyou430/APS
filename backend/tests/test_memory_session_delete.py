from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import (
    MemoryCaptureSource,
    MemoryRecord,
    MemoryRetrievalEvent,
    MemorySourceLink,
)


pytestmark = pytest.mark.asyncio


async def test_session_delete_removes_candidates_and_tombstones_confirmed_source(
    client: AsyncClient,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import memory_capture

    monkeypatch.setattr(
        memory_capture,
        "get_settings",
        lambda: SimpleNamespace(
            memory_extraction_enabled=True,
            memory_capture_ttl_hours=24,
            memory_extraction_provider="fake",
            memory_extraction_provider_version="test-v1",
        ),
    )
    session_response = await client.post(
        "/api/chat/sessions",
        headers=admin_headers,
        json={"title": "Delete memory sources", "surface": "knowledge"},
    )
    session_id = session_response.json()["id"]
    stream = await client.post(
        f"/api/chat/sessions/{session_id}/messages",
        headers=admin_headers,
        json={"content": "Remember the deadline is Friday."},
    )
    assert stream.status_code == 200

    async with SessionLocal() as db:
        source = await db.scalar(
            select(MemoryCaptureSource).where(
                MemoryCaptureSource.chat_session_id == session_id
            )
        )
        assert source is not None
        active = MemoryRecord(
            memory_id="confirmed-session-memory",
            organization_id=1,
            user_id=1,
            content="Deadline is Friday",
            type="fact",
            layer="L1",
            status="active",
            origin="extracted",
            revision=1,
            metadata_={},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        candidate = MemoryRecord(
            memory_id="candidate-session-memory",
            organization_id=1,
            user_id=1,
            content="Unconfirmed",
            type="context",
            layer="L1",
            status="candidate",
            origin="extracted",
            revision=1,
            metadata_={},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db.add_all([active, candidate])
        await db.flush()
        retrieval_event = MemoryRetrievalEvent(
            organization_id=1,
            user_id=1,
            chat_session_id=session_id,
            query_hmac="e" * 64,
            query_hmac_version=1,
            memory_mode="auto",
            retrieval_mode="fts",
            result_count=1,
            latency_ms=1,
            outcome="success",
        )
        db.add(retrieval_event)
        db.add_all(
            [
                MemorySourceLink(
                    organization_id=1,
                    user_id=1,
                    memory_id=active.memory_id,
                    source_id=source.id,
                    source_label="turn-source",
                ),
                MemorySourceLink(
                    organization_id=1,
                    user_id=1,
                    memory_id=candidate.memory_id,
                    source_id=source.id,
                    source_label="turn-source",
                ),
            ]
        )
        await db.commit()
        retrieval_event_id = retrieval_event.id

    deleted = await client.delete(
        f"/api/chat/sessions/{session_id}", headers=admin_headers
    )
    assert deleted.status_code == 204

    async with SessionLocal() as db:
        assert await db.get(MemoryRecord, "candidate-session-memory") is None
        retained = await db.get(MemoryRecord, "confirmed-session-memory")
        assert retained is not None
        link = await db.scalar(
            select(MemorySourceLink).where(
                MemorySourceLink.memory_id == "confirmed-session-memory"
            )
        )
        assert link is not None
        assert link.source_id is None
        assert link.source_tombstoned is True
        assert link.source_label == "source-unavailable"
        assert link.source_content_sha256 == source.content_sha256
        retained_event = await db.get(MemoryRetrievalEvent, retrieval_event_id)
        assert retained_event is not None
        assert retained_event.organization_id == 1
        assert retained_event.user_id == 1
        assert retained_event.chat_session_id is None
