from __future__ import annotations

import base64
import json

from sqlalchemy import select, text

import pytest
from httpx import AsyncClient

from app.database import SessionLocal
from app.models import AuditEvent
from app.services import memory_repository
from app.services.memory_repository import list_active_memories


pytestmark = pytest.mark.asyncio


async def create_memory(
    client: AsyncClient,
    headers: dict[str, str],
    content: str,
    *,
    memory_type: str = "fact",
) -> dict:
    response = await client.post(
        "/api/memory",
        headers=headers,
        json={"content": content, "type": memory_type, "metadata": {"source": "manual"}},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_manual_memory_is_active_and_persisted_in_database(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    created = await create_memory(
        client,
        admin_headers,
        "The quarterly planning window closes on Friday.",
        memory_type="decision",
    )

    assert isinstance(created["memory_id"], str)
    assert created["revision"] == 1
    assert created["layer"] == "L1"
    assert created["status"] == "active"
    assert created["origin"] == "manual"
    assert created["source_summary"] is None

    async with SessionLocal() as db:
        row = (
            await db.execute(
                text(
                    "SELECT memory_id, revision, status, origin, content "
                    "FROM memory_records WHERE memory_id = :memory_id"
                ),
                {"memory_id": created["memory_id"]},
            )
        ).one()

    assert row.memory_id == created["memory_id"]
    assert row.revision == 1
    assert row.status == "active"
    assert row.origin == "manual"
    assert row.content == created["content"]

    fetched = await client.get(
        f"/api/memory/{created['memory_id']}",
        headers=admin_headers,
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json() == created


async def test_memory_update_and_delete_require_matching_revision(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    secret = "A memory body that must never appear in audit metadata."
    created = await create_memory(client, admin_headers, secret, memory_type="preference")
    memory_id = created["memory_id"]

    updated = await client.put(
        f"/api/memory/{memory_id}",
        headers=admin_headers,
        json={"content": "Use concise status reports.", "expected_revision": 1},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["revision"] == 2
    assert updated.json()["content"] == "Use concise status reports."

    stale_update = await client.put(
        f"/api/memory/{memory_id}",
        headers=admin_headers,
        json={"content": "Stale overwrite", "expected_revision": 1},
    )
    assert stale_update.status_code == 409

    stale_delete = await client.delete(
        f"/api/memory/{memory_id}",
        headers=admin_headers,
        params={"expected_revision": 1},
    )
    assert stale_delete.status_code == 409

    deleted = await client.delete(
        f"/api/memory/{memory_id}",
        headers=admin_headers,
        params={"expected_revision": 2},
    )
    assert deleted.status_code == 204, deleted.text
    assert (await client.get(f"/api/memory/{memory_id}", headers=admin_headers)).status_code == 404

    async with SessionLocal() as db:
        remaining = await db.scalar(
            text("SELECT count(*) FROM memory_records WHERE memory_id = :memory_id"),
            {"memory_id": memory_id},
        )
        audits = list(
            (
                await db.scalars(
                    select(AuditEvent).where(
                        AuditEvent.resource_type == "memory",
                        AuditEvent.resource_id == memory_id,
                    )
                )
            ).all()
        )

    assert remaining == 0
    assert [event.action for event in audits] == [
        "memory.create",
        "memory.update",
        "memory.delete",
    ]
    assert secret not in str([event.details for event in audits])
    assert "Use concise status reports." not in str([event.details for event in audits])


async def test_memory_list_uses_owner_scoped_keyset_and_filters(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    first = await create_memory(client, admin_headers, "Alpha launch decision", memory_type="decision")
    second = await create_memory(client, admin_headers, "Beta preference", memory_type="preference")
    third = await create_memory(client, admin_headers, "Gamma decision", memory_type="decision")

    page_one = await client.get(
        "/api/memory",
        headers=admin_headers,
        params={"type": "decision", "limit": 1},
    )
    assert page_one.status_code == 200, page_one.text
    assert page_one.json()["provider"] == "platform-postgres"
    assert len(page_one.json()["items"]) == 1
    first_page_id = page_one.json()["items"][0]["memory_id"]
    cursor = page_one.json()["next_cursor"]
    assert isinstance(cursor, str) and cursor

    page_two = await client.get(
        "/api/memory",
        headers=admin_headers,
        params={"type": "decision", "limit": 1, "cursor": cursor},
    )
    assert page_two.status_code == 200, page_two.text
    second_page_id = page_two.json()["items"][0]["memory_id"]
    assert {first_page_id, second_page_id} == {first["memory_id"], third["memory_id"]}
    assert first_page_id != second_page_id
    assert page_two.json()["next_cursor"] is None

    search = await client.get(
        "/api/memory",
        headers=admin_headers,
        params={"query": "Beta", "limit": 10},
    )
    assert search.status_code == 200, search.text
    assert [item["memory_id"] for item in search.json()["items"]] == [second["memory_id"]]

    invalid_cursor = await client.get(
        "/api/memory",
        headers=admin_headers,
        params={"cursor": "not-a-valid-cursor"},
    )
    assert invalid_cursor.status_code == 422

    naive_cursor = base64.urlsafe_b64encode(
        json.dumps(["2026-08-12T10:00:00", "short-id"]).encode()
    ).decode()
    strict_cursor = await client.get(
        "/api/memory",
        headers=admin_headers,
        params={"cursor": naive_cursor},
    )
    assert strict_cursor.status_code == 422


async def test_memory_search_uses_authorized_retrieval_before_keyset(
    client: AsyncClient,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = await create_memory(client, admin_headers, "Hybrid search marker")
    calls: list[tuple[int, int, str, tuple[str, ...]]] = []

    async with SessionLocal() as db:
        record = await db.scalar(
            select(memory_repository.MemoryRecord).where(
                memory_repository.MemoryRecord.memory_id == created["memory_id"]
            )
        )
        assert record is not None

        async def retrieve(db_arg, *, scope, query, limit, memory_types):
            assert db_arg is db
            calls.append(
                (scope.organization_id, scope.user_id, query, tuple(memory_types or ()))
            )
            assert limit == 100
            return [record]

        monkeypatch.setattr(memory_repository, "retrieve_authorized_memories", retrieve)
        page = await list_active_memories(
            db,
            organization_id=1,
            user_id=1,
            query="Hybrid marker",
            memory_type="fact",
            cursor=None,
            limit=10,
        )

    assert [item.memory_id for item in page.items] == [created["memory_id"]]
    assert calls == [(1, 1, "Hybrid marker", ("fact",))]
