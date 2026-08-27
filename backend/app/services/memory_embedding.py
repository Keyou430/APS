"""Memory embedding job 服务（master §7.2）。

业务事务只写 Memory 行与 embedding job；provider 调用发生在数据库事务之外；写回使用
memory revision/CAS 短事务。Memory 已删除或 revision 已变化时丢弃结果（terminal 且不写向量）。
无 provider 时记录置为 not_configured，不写向量，仍可被 owner-scoped FTS 检索。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.models import MemoryEmbeddingJob, MemoryRecord
from app.services.embedding_client import (
    EmbeddingClient,
    EmbeddingInvalidDimension,
    EmbeddingUnavailable,
)
from app.services.memory_retrieval import MemoryEmbeddingProvider

EMBEDDING_DIMENSIONS = 1024


def build_memory_embedding_provider(
    settings: Settings | None = None,
) -> MemoryEmbeddingProvider | None:
    resolved = settings or get_settings()
    if not resolved.memory_embedding_enabled:
        return None
    api_url = resolved.memory_embedding_api_url
    api_key = resolved.memory_embedding_api_key
    if not api_url or api_key is None:
        return None
    return EmbeddingClient(
        base_url=api_url,
        api_key=api_key,
        timeout_seconds=resolved.memory_embedding_timeout_seconds,
    )


async def recover_stale_embedding_jobs(
    db: AsyncSession,
    *,
    stale_after_seconds: float,
    now: datetime | None = None,
) -> int:
    """worker 崩溃遗留的 processing embedding job 恢复：lease 过期后重置为 queued。"""
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(seconds=stale_after_seconds)
    result = await db.execute(
        update(MemoryEmbeddingJob)
        .where(
            MemoryEmbeddingJob.status == "processing",
            MemoryEmbeddingJob.claimed_at.is_not(None),
            MemoryEmbeddingJob.claimed_at <= cutoff,
        )
        .values(
            status="queued",
            claimed_by=None,
            claimed_at=None,
            available_at=now,
        )
    )
    return result.rowcount or 0


async def claim_due_embedding_jobs(
    db: AsyncSession,
    *,
    worker_id: str,
    limit: int = 10,
) -> list[MemoryEmbeddingJob]:
    """领取到期 embedding job；PostgreSQL 使用 FOR UPDATE SKIP LOCKED 防双 worker 重复领取。"""
    statement = (
        select(MemoryEmbeddingJob)
        .where(MemoryEmbeddingJob.status == "queued")
        .order_by(
            MemoryEmbeddingJob.available_at,
            MemoryEmbeddingJob.created_at,
            MemoryEmbeddingJob.id,
        )
        .limit(limit)
    )
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)
    jobs = list((await db.scalars(statement)).all())
    now = datetime.now(UTC)
    for job in jobs:
        job.status = "processing"
        job.claimed_at = now
        job.claimed_by = worker_id
    await db.flush()
    return jobs


async def prepare_embedding_job(
    db: AsyncSession,
    job: MemoryEmbeddingJob,
) -> str | None:
    """在短事务中校验 job 有效性并返回待向量化文本。

    记录已删除或 revision 已变化时 job 直接终态（completed + error_code），不调用 provider。
    """
    record = await db.scalar(
        select(MemoryRecord).where(
            MemoryRecord.memory_id == job.memory_id,
            MemoryRecord.organization_id == job.organization_id,
            MemoryRecord.user_id == job.user_id,
        )
    )
    if record is None:
        job.status = "completed"
        job.completed_at = datetime.now(UTC)
        job.last_error_code = "record_deleted"
        return None
    if record.revision != job.revision:
        job.status = "completed"
        job.completed_at = datetime.now(UTC)
        job.last_error_code = "stale_revision"
        return None
    if record.embedding_state not in {"pending", "failed"}:
        job.status = "completed"
        job.completed_at = datetime.now(UTC)
        job.last_error_code = "state_conflict"
        return None
    return record.content


async def write_embedding_result(
    db: AsyncSession,
    job: MemoryEmbeddingJob,
    *,
    vector: list[float] | None,
    error_code: str | None,
) -> None:
    """在 revision/CAS 短事务中写回结果；revision 不匹配或记录已删除时丢弃结果。"""
    now = datetime.now(UTC)
    if error_code is not None:
        job.attempts += 1
        job.status = "failed"
        job.completed_at = now
        job.last_error_code = error_code
        await db.execute(
            update(MemoryRecord)
            .where(
                MemoryRecord.memory_id == job.memory_id,
                MemoryRecord.organization_id == job.organization_id,
                MemoryRecord.user_id == job.user_id,
                MemoryRecord.revision == job.revision,
            )
            .values(embedding_state="failed")
        )
        return
    if vector is None:
        # 无 provider：不写向量，状态收敛为 not_configured，FTS 立即可用。
        result = await db.execute(
            update(MemoryRecord)
            .where(
                MemoryRecord.memory_id == job.memory_id,
                MemoryRecord.organization_id == job.organization_id,
                MemoryRecord.user_id == job.user_id,
                MemoryRecord.revision == job.revision,
            )
            .values(embedding_state="not_configured")
        )
    else:
        settings = get_settings()
        result = await db.execute(
            update(MemoryRecord)
            .where(
                MemoryRecord.memory_id == job.memory_id,
                MemoryRecord.organization_id == job.organization_id,
                MemoryRecord.user_id == job.user_id,
                MemoryRecord.revision == job.revision,
            )
            .values(
                embedding=vector,
                embedding_state="ready",
                embedding_model=settings.memory_embedding_model,
                embedding_version="v1",
                embedding_updated_at=now,
            )
        )
    if result.rowcount == 0:
        job.status = "completed"
        job.completed_at = now
        job.last_error_code = "stale_revision"
        return
    job.status = "completed"
    job.completed_at = now


async def run_embedding_cycle(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    provider: MemoryEmbeddingProvider | None,
    worker_id: str,
    limit: int = 10,
) -> int:
    """一个领取周期：claim（短事务）→ 事务外 provider 调用 → CAS 写回（短事务）。"""
    processed = 0
    settings = get_settings()
    async with session_factory() as db:
        await recover_stale_embedding_jobs(
            db, stale_after_seconds=settings.memory_worker_lease_seconds
        )
        jobs = await claim_due_embedding_jobs(db, worker_id=worker_id, limit=limit)
        await db.commit()
    for claimed in jobs:
        content: str | None = None
        async with session_factory() as db:
            job = await db.get(MemoryEmbeddingJob, claimed.id)
            if job is not None:
                content = await prepare_embedding_job(db, job)
            await db.commit()
        if content is None:
            processed += 1
            continue
        vector: list[float] | None = None
        error_code: str | None = None
        if provider is not None:
            try:
                vectors = await provider.embed([content])
                if len(vectors) != 1 or len(vectors[0]) != EMBEDDING_DIMENSIONS:
                    raise EmbeddingInvalidDimension("embedding_invalid_dimension")
                vector = vectors[0]
            except EmbeddingUnavailable as error:
                error_code = str(error)
            except EmbeddingInvalidDimension as error:
                error_code = str(error)
        async with session_factory() as db:
            job = await db.get(MemoryEmbeddingJob, claimed.id)
            if job is not None and job.status == "processing":
                await write_embedding_result(db, job, vector=vector, error_code=error_code)
            await db.commit()
        processed += 1
    return processed
