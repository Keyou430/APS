"""Memory embedding job worker 契约测试（master §7.2 / D1.2）。

- 双 worker 不能领取同一 job（claim 状态转换）。
- revision 变化或记录已删除时丢弃 provider 结果，不写向量。
- 无 provider 时状态收敛为 not_configured，FTS 仍可用。
- provider 成功时在 revision/CAS 短事务写回向量并置 ready。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

import pytest

from app.database import SessionLocal
from app.models import MemoryEmbeddingJob, MemoryRecord, OrganizationMembership
from app.services.memory_embedding import (
    claim_due_embedding_jobs,
    prepare_embedding_job,
    recover_stale_embedding_jobs,
    run_embedding_cycle,
    write_embedding_result,
)

pytestmark = pytest.mark.asyncio


class _FakeEmbedding:
    def __init__(self, vectors: list[list[float]] | None = None) -> None:
        self._vectors = vectors or [[0.5] * 1024]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vectors[i % len(self._vectors)] for i in range(len(texts))]


async def _make_record_with_job(
    *,
    content: str = "embedding probe",
    revision: int = 1,
    state: str = "pending",
) -> tuple[str, MemoryEmbeddingJob]:
    async with SessionLocal() as db:
        membership = await db.scalar(select(OrganizationMembership).limit(1))
        assert membership is not None
        record = MemoryRecord(
            memory_id=f"jobprobe{abs(hash(content)) % 10**9:09d}",
            organization_id=membership.organization_id,
            user_id=membership.user_id,
            content=content,
            type="fact",
            layer="L1",
            status="active",
            origin="manual",
            revision=revision,
            embedding_state=state,
        )
        db.add(record)
        await db.flush()
        job = MemoryEmbeddingJob(
            organization_id=record.organization_id,
            user_id=record.user_id,
            memory_id=record.memory_id,
            revision=revision,
            status="queued",
        )
        db.add(job)
        await db.commit()
        return record.memory_id, job


async def test_two_workers_cannot_claim_the_same_embedding_job() -> None:
    async with SessionLocal() as db:
        membership = await db.scalar(select(OrganizationMembership).limit(1))
        assert membership is not None
        record = MemoryRecord(
            memory_id="claimprobe0000000000000000000000",
            organization_id=membership.organization_id,
            user_id=membership.user_id,
            content="claim probe",
            type="fact",
            layer="L1",
            status="active",
            origin="manual",
            revision=1,
            embedding_state="pending",
        )
        db.add(record)
        await db.flush()
        db.add_all(
            [
                MemoryEmbeddingJob(
                    organization_id=membership.organization_id,
                    user_id=membership.user_id,
                    memory_id=record.memory_id,
                    revision=1,
                    status="queued",
                ),
                MemoryEmbeddingJob(
                    organization_id=membership.organization_id,
                    user_id=membership.user_id,
                    memory_id=record.memory_id,
                    revision=1,
                    status="queued",
                ),
            ]
        )
        await db.commit()

    async with SessionLocal() as db:
        first = await claim_due_embedding_jobs(db, worker_id="worker-a", limit=1)
        await db.commit()
    async with SessionLocal() as db:
        second = await claim_due_embedding_jobs(db, worker_id="worker-b", limit=1)
        await db.commit()

    assert len(first) == 1 and len(second) == 1
    assert first[0].id != second[0].id
    assert {first[0].claimed_by, second[0].claimed_by} == {"worker-a", "worker-b"}


async def test_crashed_embedding_job_is_recoverable_after_lease_expiry() -> None:
    memory_id, _job = await _make_record_with_job(content="crash probe")
    async with SessionLocal() as db:
        claimed = await claim_due_embedding_jobs(db, worker_id="worker-a", limit=1)
        await db.commit()
    assert len(claimed) == 1 and claimed[0].status == "processing"

    async with SessionLocal() as db:
        job = await db.get(MemoryEmbeddingJob, claimed[0].id)
        assert job is not None
        job.claimed_at = datetime.now(UTC) - timedelta(seconds=600)
        await db.commit()

    async with SessionLocal() as db:
        recovered_count = await recover_stale_embedding_jobs(db, stale_after_seconds=300)
        await db.commit()
        job = await db.get(MemoryEmbeddingJob, claimed[0].id)
        assert recovered_count == 1
        assert job is not None and job.status == "queued"
        assert job.claimed_by is None and job.claimed_at is None

    async with SessionLocal() as db:
        re_claimed = await claim_due_embedding_jobs(db, worker_id="worker-b", limit=1)
        await db.commit()
    assert len(re_claimed) == 1
    assert re_claimed[0].id == claimed[0].id
    assert re_claimed[0].claimed_by == "worker-b"


async def test_stale_revision_discards_embedding_result() -> None:
    memory_id, job = await _make_record_with_job(content="stale probe", revision=2)
    async with SessionLocal() as db:
        stale = MemoryEmbeddingJob(
            organization_id=job.organization_id,
            user_id=job.user_id,
            memory_id=memory_id,
            revision=1,
            status="queued",
        )
        db.add(stale)
        await db.commit()
        content = await prepare_embedding_job(db, stale)
        await db.commit()

    assert content is None
    assert stale.status == "completed"
    assert stale.last_error_code == "stale_revision"

    async with SessionLocal() as db:
        record = await db.scalar(
            select(MemoryRecord).where(MemoryRecord.memory_id == memory_id)
        )
        assert record is not None
        assert record.embedding is None, "stale 结果不得写回向量"


async def test_no_provider_converges_to_not_configured_and_keeps_fts() -> None:
    memory_id, _job = await _make_record_with_job(content="no provider probe")
    processed = await run_embedding_cycle(
        SessionLocal,
        provider=None,
        worker_id="worker-no-provider",
    )
    assert processed >= 1
    async with SessionLocal() as db:
        record = await db.scalar(
            select(MemoryRecord).where(MemoryRecord.memory_id == memory_id)
        )
        job = await db.scalar(
            select(MemoryEmbeddingJob).where(MemoryEmbeddingJob.memory_id == memory_id)
        )
        assert record is not None
        assert record.embedding_state == "not_configured"
        assert record.embedding is None
        assert job is not None and job.status == "completed"


async def test_provider_success_writes_vector_with_cas() -> None:
    memory_id, job = await _make_record_with_job(content="provider probe", revision=1)
    async with SessionLocal() as db:
        job = await db.get(MemoryEmbeddingJob, job.id)
        assert job is not None
        content = await prepare_embedding_job(db, job)
        await db.commit()
    assert content == "provider probe"
    async with SessionLocal() as db:
        job = await db.get(MemoryEmbeddingJob, job.id)
        assert job is not None
        await write_embedding_result(db, job, vector=[0.25] * 1024, error_code=None)
        await db.commit()

    async with SessionLocal() as db:
        record = await db.scalar(
            select(MemoryRecord).where(MemoryRecord.memory_id == memory_id)
        )
        assert record is not None
        assert record.embedding_state == "ready"
        assert record.embedding == [0.25] * 1024
        assert record.embedding_model == "text-embedding-v4"
        assert record.embedding_version == "v1"
