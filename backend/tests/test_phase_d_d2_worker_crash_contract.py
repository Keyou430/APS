"""D2 RED：执行计划 2026-08-15 D2.1/D2 Gate 的 worker 崩溃恢复契约。

D2 Gate 要求 "worker crash/retry/dedup、session deletion、日志脱敏全部通过"。
现有实现：claim 只扫描 status='queued'；fail() 要求 claimed_by 匹配。worker 在 claim 提交后、
provider 完成前崩溃时，job 停留在 processing 且无 lease 恢复路径，永远无法重新领取。
本文件 RED 只证明该业务能力缺失；另保留一条"lease 未过期不得抢占"的文档性测试。
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import hashlib

from sqlalchemy import select

import pytest

from app.database import SessionLocal
from app.models import MemoryCaptureSource, MemoryExtractionJob, OrganizationMembership
from app.workers.memory_worker import (
    SqlAlchemyMemoryJobStore,
    recover_stale_extraction_jobs,
)

pytestmark = pytest.mark.asyncio


async def _seed_source_and_job(content: str = "crash probe") -> tuple[int, int]:
    async with SessionLocal() as db:
        membership = await db.scalar(select(OrganizationMembership).limit(1))
        assert membership is not None
        now = datetime.now(UTC)
        source = MemoryCaptureSource(
            source_id=uuid4().hex,
            organization_id=membership.organization_id,
            user_id=membership.user_id,
            chat_session_id=None,
            chat_turn_id=None,
            source_kind="user_text",
            raw_text=content,
            content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            status="queued",
            expires_at=now + timedelta(hours=24),
            created_at=now,
        )
        db.add(source)
        await db.flush()
        job = MemoryExtractionJob(
            organization_id=membership.organization_id,
            user_id=membership.user_id,
            source_id=source.id,
            status="queued",
            provider="fake",
            provider_version="test-v1",
        )
        db.add(job)
        await db.commit()
        return source.id, job.id


async def test_abandoned_processing_job_is_recoverable_after_worker_crash() -> None:
    source_id, job_id = await _seed_source_and_job()
    first = SqlAlchemyMemoryJobStore(SessionLocal, retry_delay_seconds=0)
    claim = await first.claim("worker-a")
    assert claim is not None and claim.job_id == job_id

    # worker-a 在 provider 调用前崩溃：job 停留在 processing，claimed_at 已持久化。
    async with SessionLocal() as db:
        job = await db.get(MemoryExtractionJob, job_id)
        assert job is not None
        assert job.status == "processing" and job.claimed_by == "worker-a"
        # 模拟崩溃后 lease 过期：claimed_at 拨回 lease 窗口外。
        job.claimed_at = datetime.now(UTC) - timedelta(seconds=600)
        await db.commit()

    restarted = SqlAlchemyMemoryJobStore(SessionLocal, retry_delay_seconds=0)
    recovered = await restarted.claim("worker-b")
    assert recovered is not None, (
        "D2 Gate 要求 worker crash 后 job 可恢复；当前 claim 只扫描 status='queued'，"
        "崩溃遗留的 processing job 永远无法重新领取（业务能力缺失）"
    )
    assert recovered.job_id == job_id
    async with SessionLocal() as db:
        job = await db.get(MemoryExtractionJob, job_id)
        assert job is not None
        assert job.status == "processing" and job.claimed_by == "worker-b"
        assert job.attempts == 2, "恢复不消耗 attempt；重新领取算一次新尝试"


async def test_recovery_resets_only_stale_processing_jobs_and_preserves_attempts() -> None:
    source_a, job_a = await _seed_source_and_job(content="stale lease probe")
    source_b, job_b = await _seed_source_and_job(content="fresh lease probe")
    first = SqlAlchemyMemoryJobStore(SessionLocal, retry_delay_seconds=0)
    claim_a = await first.claim("worker-a")
    claim_b = await first.claim("worker-a")
    assert claim_a is not None and claim_b is not None

    async with SessionLocal() as db:
        stale = await db.get(MemoryExtractionJob, job_a)
        assert stale is not None
        stale.claimed_at = datetime.now(UTC) - timedelta(seconds=600)
        await db.commit()

    async with SessionLocal() as db:
        recovered = await recover_stale_extraction_jobs(db, stale_after_seconds=300)
        await db.commit()
        stale = await db.get(MemoryExtractionJob, job_a)
        fresh = await db.get(MemoryExtractionJob, job_b)
        assert recovered == 1, "只恢复 lease 已过期的 processing job"
        assert stale is not None and stale.status == "queued"
        assert stale.claimed_by is None and stale.claimed_at is None
        assert stale.attempts == 1, "恢复不得额外消耗 attempt 预算"
        assert fresh is not None and fresh.status == "processing"
        assert fresh.claimed_by == "worker-a", "lease 未过期的 job 不得被重置"


async def test_processing_job_is_not_stolen_while_lease_active() -> None:
    source_id, job_id = await _seed_source_and_job(content="no steal probe")
    first = SqlAlchemyMemoryJobStore(SessionLocal, retry_delay_seconds=0)
    claim = await first.claim("worker-a")
    assert claim is not None and claim.job_id == job_id

    second = SqlAlchemyMemoryJobStore(SessionLocal, retry_delay_seconds=0)
    assert await second.claim("worker-b") is None, "lease 未过期时不得抢占 processing job"

    await first.fail(claim, "provider_timeout")
    async with SessionLocal() as db:
        job = await db.get(MemoryExtractionJob, job_id)
        assert job is not None
        assert job.status == "queued", "正常失败路径应回到 queued 并保留 attempt 预算"
