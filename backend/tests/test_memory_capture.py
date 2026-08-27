from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import MemoryCaptureSource, MemoryExtractionJob

from app.services.memory_capture import (
    CaptureInput,
    CapturePolicyDecision,
    build_capture_snapshot,
    enqueue_capture_source,
    purge_expired_sources,
    should_capture_user_text,
)


def test_capture_policy_accepts_only_bounded_user_authored_text() -> None:
    accepted = CaptureInput(
        organization_id=1,
        user_id=7,
        session_id=9,
        turn_id=11,
        text="Remember that Friday is the planning deadline.",
        source_kind="user_text",
        turn_status="completed",
        created_at=datetime.now(UTC),
    )
    decision = should_capture_user_text(accepted)
    assert decision is CapturePolicyDecision.ACCEPT
    snapshot = build_capture_snapshot(accepted)
    assert snapshot.organization_id == 1
    assert snapshot.user_id == 7
    assert snapshot.chat_session_id == 9
    assert snapshot.chat_turn_id == 11
    assert snapshot.raw_text == accepted.text
    assert len(snapshot.content_sha256) == 64


@pytest.mark.parametrize(
    "source_kind,text,turn_status",
    [
        ("attachment", "attachment body", "completed"),
        ("link", "linked page body", "completed"),
        ("assistant", "assistant output", "completed"),
        ("tool", "tool output", "completed"),
        ("fixed_context", "company policy", "completed"),
        ("dingtalk_document", "document body", "completed"),
        ("skill", "filesystem skill", "completed"),
        ("user_text", "secret@example.com password=abc", "completed"),
        ("user_text", "employee diagnosis and national id 110101", "completed"),
        ("user_text", "employee salary is 50000", "completed"),
        ("user_text", "disciplinary action for employee", "completed"),
        ("user_text", "employee health record", "completed"),
        ("user_text", "员工身份证号码待核验", "completed"),
        ("user_text", "员工工资记录", "completed"),
        ("user_text", "completed but interrupted", "interrupted"),
        ("user_text", "failed response", "failed"),
    ],
)
def test_capture_policy_rejects_non_user_or_unsafe_inputs(
    source_kind: str, text: str, turn_status: str
) -> None:
    payload = CaptureInput(
        organization_id=1,
        user_id=7,
        session_id=9,
        turn_id=11,
        text=text,
        source_kind=source_kind,
        turn_status=turn_status,
        created_at=datetime.now(UTC),
    )
    assert should_capture_user_text(payload) is CapturePolicyDecision.REJECT


def test_capture_policy_rejects_text_over_4k_utf8_bytes_and_build_is_bounded() -> None:
    payload = CaptureInput(
        organization_id=1,
        user_id=7,
        session_id=9,
        turn_id=11,
        text="记" * 4097,
        source_kind="user_text",
        turn_status="completed",
        created_at=datetime.now(UTC),
    )
    assert should_capture_user_text(payload) is CapturePolicyDecision.REJECT
    with pytest.raises(ValueError, match="4096"):
        build_capture_snapshot(payload)


@pytest.mark.asyncio
async def test_successful_chat_completion_persists_only_bounded_user_text_source(
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
    session = await client.post(
        "/api/chat/sessions",
        headers=admin_headers,
        json={"title": "Capture API", "surface": "knowledge"},
    )
    assert session.status_code == 201, session.text
    response = await client.post(
        f"/api/chat/sessions/{session.json()['id']}/messages",
        headers=admin_headers,
        json={"content": "Remember the Friday planning deadline."},
    )
    assert response.status_code == 200, response.text

    async with SessionLocal() as db:
        source = await db.scalar(
            select(MemoryCaptureSource).where(
                MemoryCaptureSource.chat_session_id == session.json()["id"]
            )
        )
    assert source is not None
    assert source.source_kind == "user_text"
    assert source.raw_text == "Remember the Friday planning deadline."
    assert len(source.raw_text.encode("utf-8")) <= 4096


@pytest.mark.asyncio
async def test_capture_replay_is_idempotent_and_purge_only_clears_terminal_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import memory_capture

    now = datetime.now(UTC)
    monkeypatch.setattr(
        memory_capture,
        "get_settings",
        lambda: SimpleNamespace(
            memory_extraction_enabled=True,
            memory_capture_ttl_hours=1,
            memory_extraction_provider="fake",
            memory_extraction_provider_version="test-v1",
        ),
    )
    payload = CaptureInput(
        organization_id=1,
        user_id=1,
        session_id=1,
        turn_id=1,
        text="Replay-safe synthetic capture.",
        source_kind="user_text",
        turn_status="completed",
        created_at=now - timedelta(hours=2),
    )
    async with SessionLocal() as db:
        first = await enqueue_capture_source(db, payload)
        await db.commit()
        second = await enqueue_capture_source(db, payload)
        assert first is not None and second is not None and first.id == second.id
        source_count = await db.scalar(select(func.count()).select_from(MemoryCaptureSource))
        job_count = await db.scalar(select(func.count()).select_from(MemoryExtractionJob))
        assert source_count == 1 and job_count == 1

        assert await purge_expired_sources(db, now=now) == 0
        first.status = "completed"
        await db.flush()
        assert await purge_expired_sources(db, now=now) == 1
        assert first.raw_text is None
        assert first.status == "purged"
