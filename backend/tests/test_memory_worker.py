from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import MemoryExtractionJob
from app.workers.memory_worker import (
    InMemoryJobClaimStore,
    MemoryWorker,
    SqlAlchemyMemoryJobStore,
)


@pytest.mark.asyncio
async def test_two_workers_cannot_claim_the_same_job() -> None:
    store = InMemoryJobClaimStore(["job-1"])
    first, second = await asyncio.gather(store.claim("worker-a"), store.claim("worker-b"))
    assert sorted(item for item in (first, second) if item is not None) == ["job-1"]


@pytest.mark.asyncio
async def test_provider_runs_after_claim_transaction_and_retry_is_recoverable() -> None:
    events: list[str] = []

    class Store:
        attempts = 0

        async def claim(self, worker_id: str):
            self.attempts += 1
            events.append("claim-committed")
            return {"job_id": 1, "source_text": "user text", "scope_ref": "opaque"}

        async def complete(self, claim, candidates):
            events.append("completed")

        async def fail(self, claim, error_code):
            events.append(error_code)

    class Provider:
        async def extract(self, source_text: str, *, scope_ref: str):
            assert events == ["claim-committed"]
            events.append("provider-outside-transaction")
            raise TimeoutError

    worker = MemoryWorker(store=Store(), provider=Provider(), worker_id="worker-a")
    assert await worker.run_once() is True
    assert events == [
        "claim-committed",
        "provider-outside-transaction",
        "provider_timeout",
    ]


async def test_persistent_claim_retry_and_restart_recovery(
    client: AsyncClient,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

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
        json={"title": "Worker claim", "surface": "knowledge"},
    )
    streamed = await client.post(
        f"/api/chat/sessions/{session.json()['id']}/messages",
        headers=admin_headers,
        json={"content": "Remember the worker recovery marker."},
    )
    assert streamed.status_code == 200, streamed.text
    async with SessionLocal() as db:
        job = await db.scalar(select(MemoryExtractionJob))
        assert job is not None
        job.max_attempts = 2
        await db.commit()

    first_store = SqlAlchemyMemoryJobStore(SessionLocal, retry_delay_seconds=0)
    second_store = SqlAlchemyMemoryJobStore(SessionLocal, retry_delay_seconds=0)
    first, second = await asyncio.gather(
        first_store.claim("worker-a"),
        second_store.claim("worker-b"),
    )
    claims = [claim for claim in (first, second) if claim is not None]
    assert len(claims) == 1
    await first_store.fail(claims[0], "provider_timeout")

    restarted_store = SqlAlchemyMemoryJobStore(SessionLocal, retry_delay_seconds=0)
    recovered = await restarted_store.claim("worker-after-restart")
    assert recovered is not None
    assert recovered.job_id == claims[0].job_id
    await restarted_store.fail(recovered, "provider_timeout")

    async with SessionLocal() as db:
        job = await db.get(MemoryExtractionJob, recovered.job_id)
        assert job is not None
        assert job.status == "failed"
        assert job.attempts == 2
        assert job.last_error_code == "provider_timeout"


async def test_shutdown_waits_for_inflight_provider() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    events: list[str] = []

    class Store:
        async def claim(self, worker_id: str):
            del worker_id
            return {"job_id": 1, "source_text": "text", "scope_ref": "opaque"}

        async def complete(self, claim, candidates):
            del claim, candidates
            events.append("completed")

        async def fail(self, claim, error_code):
            del claim, error_code

    class Provider:
        async def extract(self, source_text: str, *, scope_ref: str):
            del source_text, scope_ref
            started.set()
            await release.wait()
            return []

    worker = MemoryWorker(store=Store(), provider=Provider(), worker_id="worker-a")
    run = asyncio.create_task(worker.run_once())
    await started.wait()
    shutdown = asyncio.create_task(worker.shutdown())
    await asyncio.sleep(0)
    assert not shutdown.done()
    release.set()
    assert await run is True
    await shutdown
    assert events == ["completed"]
