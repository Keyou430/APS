from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from app.database import SessionLocal
from app.models import MemoryCaptureSource, MemoryRecord, MemorySourceLink


pytestmark = pytest.mark.asyncio


async def seed_candidate(*, content: str, source_ref: str) -> str:
    async with SessionLocal() as db:
        source = MemoryCaptureSource(
            source_id=source_ref,
            organization_id=1,
            user_id=1,
            source_kind="user_text",
            content_sha256=(source_ref * 64)[:64],
            status="completed",
            created_at=datetime.now(UTC),
        )
        db.add(source)
        await db.flush()
        record = MemoryRecord(
            memory_id=(source_ref * 8)[:32],
            organization_id=1,
            user_id=1,
            content=content,
            type="preference",
            layer="L2",
            status="candidate",
            origin="extracted",
            revision=1,
            metadata_={},
            source_summary=source_ref,
            confidence=0.88,
            provider="fake-extractor",
            provider_version="v1",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db.add(record)
        await db.flush()
        db.add(
            MemorySourceLink(
                organization_id=1,
                user_id=1,
                memory_id=record.memory_id,
                source_id=source.id,
                source_label=source_ref,
            )
        )
        await db.commit()
        return record.memory_id


async def test_candidates_are_owner_scoped_and_excluded_from_active_memory_list(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    memory_id = await seed_candidate(content="Candidate preference", source_ref="candidate-source-a")

    candidates = await client.get("/api/memory/candidates", headers=admin_headers)
    assert candidates.status_code == 200, candidates.text
    assert candidates.json()["provider"] == "platform-postgres"
    assert [item["memory_id"] for item in candidates.json()["items"]] == [memory_id]
    item = candidates.json()["items"][0]
    assert item["source_ref"] == "candidate-source-a"
    assert item["provider"] == "fake-extractor"

    active = await client.get("/api/memory", headers=admin_headers)
    assert active.status_code == 200
    assert memory_id not in {entry["memory_id"] for entry in active.json()["items"]}


async def test_confirm_requires_revision_and_activates_candidate(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    memory_id = await seed_candidate(content="Confirm this preference", source_ref="candidate-source-b")

    stale = await client.post(
        f"/api/memory/{memory_id}/confirm",
        headers=admin_headers,
        json={"expected_revision": 2},
    )
    assert stale.status_code == 409

    confirmed = await client.post(
        f"/api/memory/{memory_id}/confirm",
        headers=admin_headers,
        json={"expected_revision": 1},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "active"
    assert confirmed.json()["origin"] == "extracted"
    assert (
        await client.get(f"/api/memory/candidates/{memory_id}", headers=admin_headers)
    ).status_code == 404


async def test_reject_physically_deletes_candidate_and_source_link(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    memory_id = await seed_candidate(content="Reject this candidate", source_ref="candidate-source-c")

    rejected = await client.post(
        f"/api/memory/{memory_id}/reject",
        headers=admin_headers,
        json={"expected_revision": 1},
    )
    assert rejected.status_code == 204, rejected.text
    assert (await client.get(f"/api/memory/{memory_id}", headers=admin_headers)).status_code == 404


async def test_confirmed_correction_can_only_supersede_owner_active_memory(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    original = await client.post(
        "/api/memory",
        headers=admin_headers,
        json={"content": "The deadline is Thursday.", "type": "fact"},
    )
    assert original.status_code == 201, original.text
    candidate_id = await seed_candidate(
        content="The deadline is Friday.", source_ref="candidate-correction"
    )

    confirmed = await client.post(
        f"/api/memory/{candidate_id}/confirm",
        headers=admin_headers,
        json={
            "expected_revision": 1,
            "supersedes_memory_id": original.json()["memory_id"],
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    async with SessionLocal() as db:
        old = await db.get(MemoryRecord, original.json()["memory_id"])
        new = await db.get(MemoryRecord, candidate_id)
        assert old is not None and old.status == "superseded" and old.revision == 2
        assert new is not None and new.status == "active"
        assert new.supersedes_memory_id == old.memory_id

    hidden = await client.get(
        f"/api/memory/{original.json()['memory_id']}", headers=admin_headers
    )
    assert hidden.status_code == 404


async def test_candidate_cannot_supersede_unowned_memory(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    candidate_id = await seed_candidate(
        content="Owner correction", source_ref="candidate-unowned-correction"
    )
    async with SessionLocal() as db:
        db.add(
            MemoryRecord(
                memory_id="unowned-active-memory",
                organization_id=1,
                user_id=2,
                content="Other owner fact",
                type="fact",
                layer="L1",
                status="active",
                origin="manual",
                revision=1,
                metadata_={},
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await db.commit()

    response = await client.post(
        f"/api/memory/{candidate_id}/confirm",
        headers=admin_headers,
        json={
            "expected_revision": 1,
            "supersedes_memory_id": "unowned-active-memory",
        },
    )
    assert response.status_code == 404
    async with SessionLocal() as db:
        candidate = await db.get(MemoryRecord, candidate_id)
        other = await db.get(MemoryRecord, "unowned-active-memory")
        assert candidate is not None and candidate.status == "candidate"
        assert other is not None and other.status == "active"
