from __future__ import annotations

import asyncio
import signal
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from pydantic import ValidationError
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import SessionLocal
from app.models import (
    ChatSession,
    MemoryCaptureSource,
    MemoryExtractionJob,
    OrganizationMembership,
)
from app.schemas.memory import MemoryCandidateDTO
from app.services.memory_extraction import CandidateProvider, persist_candidates
from app.services.memory_capture import purge_expired_sources
from app.services.memory_extraction import ExtractionProvider
from app.services.memory_embedding import build_memory_embedding_provider, run_embedding_cycle
from app.config import get_settings


_sqlite_claim_lock = asyncio.Lock()


async def recover_stale_extraction_jobs(
    db: AsyncSession,
    *,
    stale_after_seconds: float,
    now: datetime | None = None,
) -> int:
    """worker 崩溃遗留的 processing job 恢复：lease 过期后重置为 queued（不消耗 attempt）。"""
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(seconds=stale_after_seconds)
    result = await db.execute(
        update(MemoryExtractionJob)
        .where(
            MemoryExtractionJob.status == "processing",
            MemoryExtractionJob.claimed_at.is_not(None),
            MemoryExtractionJob.claimed_at <= cutoff,
        )
        .values(
            status="queued",
            claimed_by=None,
            claimed_at=None,
            available_at=now,
        )
    )
    return result.rowcount or 0


@dataclass(frozen=True)
class MemoryJobClaim:
    job_id: int
    organization_id: int
    user_id: int
    source_id: int
    source_text: str
    scope_ref: str
    claimed_by: str


class MemoryJobStore(Protocol):
    async def claim(self, worker_id: str) -> MemoryJobClaim | dict[str, object] | None: ...

    async def complete(
        self,
        claim: MemoryJobClaim | dict[str, object],
        candidates: Sequence[MemoryCandidateDTO],
    ) -> None: ...

    async def fail(
        self,
        claim: MemoryJobClaim | dict[str, object],
        error_code: str,
    ) -> None: ...


class InMemoryJobClaimStore:
    def __init__(self, jobs: Sequence[str]) -> None:
        self._available = list(dict.fromkeys(jobs))
        self._claimed: set[str] = set()
        self._lock = asyncio.Lock()

    async def claim(self, worker_id: str) -> str | None:
        del worker_id
        async with self._lock:
            for job_id in self._available:
                if job_id not in self._claimed:
                    self._claimed.add(job_id)
                    return job_id
        return None


class SqlAlchemyMemoryJobStore:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
        *,
        retry_delay_seconds: int = 5,
    ) -> None:
        self._session_factory = session_factory
        self._retry_delay = timedelta(seconds=retry_delay_seconds)

    async def claim(self, worker_id: str) -> MemoryJobClaim | None:
        async with self._session_factory() as db:
            await recover_stale_extraction_jobs(
                db, stale_after_seconds=get_settings().memory_worker_lease_seconds
            )
            if db.get_bind().dialect.name == "sqlite":
                async with _sqlite_claim_lock:
                    return await self._claim_in_transaction(db, worker_id)
            return await self._claim_in_transaction(db, worker_id)

    async def _claim_in_transaction(
        self,
        db: AsyncSession,
        worker_id: str,
    ) -> MemoryJobClaim | None:
        now = datetime.now(UTC)
        statement = (
            select(MemoryExtractionJob)
            .join(
                MemoryCaptureSource,
                MemoryCaptureSource.id == MemoryExtractionJob.source_id,
            )
            .join(
                OrganizationMembership,
                (OrganizationMembership.organization_id == MemoryExtractionJob.organization_id)
                & (OrganizationMembership.user_id == MemoryExtractionJob.user_id),
            )
            .where(
                MemoryExtractionJob.status == "queued",
                MemoryExtractionJob.available_at <= now,
                MemoryExtractionJob.attempts < MemoryExtractionJob.max_attempts,
                MemoryCaptureSource.status == "queued",
                MemoryCaptureSource.raw_text.is_not(None),
                OrganizationMembership.is_active.is_(True),
                or_(
                    OrganizationMembership.expires_at.is_(None),
                    OrganizationMembership.expires_at > now,
                ),
            )
            .order_by(
                MemoryExtractionJob.available_at,
                MemoryExtractionJob.created_at,
                MemoryExtractionJob.id,
            )
            .limit(1)
        )
        if db.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update(skip_locked=True, of=MemoryExtractionJob)
        job = await db.scalar(statement)
        if job is None:
            await db.rollback()
            return None
        source = await db.get(MemoryCaptureSource, job.source_id)
        if source is None or source.raw_text is None:
            job.status = "cancelled"
            job.completed_at = now
            await db.commit()
            return None
        job.status = "processing"
        job.claimed_by = worker_id
        job.claimed_at = now
        job.attempts += 1
        claim = MemoryJobClaim(
            job_id=job.id,
            organization_id=job.organization_id,
            user_id=job.user_id,
            source_id=source.id,
            source_text=source.raw_text,
            scope_ref=source.source_id,
            claimed_by=worker_id,
        )
        await db.commit()
        return claim

    async def complete(
        self,
        claim: MemoryJobClaim | dict[str, object],
        candidates: Sequence[MemoryCandidateDTO],
    ) -> None:
        claim = _coerce_claim(claim)
        async with self._session_factory() as db:
            job = await db.scalar(
                select(MemoryExtractionJob)
                .where(
                    MemoryExtractionJob.id == claim.job_id,
                    MemoryExtractionJob.organization_id == claim.organization_id,
                    MemoryExtractionJob.user_id == claim.user_id,
                )
                .with_for_update()
            )
            source = await db.scalar(
                select(MemoryCaptureSource)
                .where(
                    MemoryCaptureSource.id == claim.source_id,
                    MemoryCaptureSource.organization_id == claim.organization_id,
                    MemoryCaptureSource.user_id == claim.user_id,
                )
                .with_for_update()
            )
            if job is None or source is None:
                await db.rollback()
                return
            if job.status != "processing" or job.claimed_by != claim.claimed_by:
                await db.rollback()
                return
            membership = await db.scalar(
                select(OrganizationMembership.id).where(
                    OrganizationMembership.organization_id == claim.organization_id,
                    OrganizationMembership.user_id == claim.user_id,
                    OrganizationMembership.is_active.is_(True),
                    or_(
                        OrganizationMembership.expires_at.is_(None),
                        OrganizationMembership.expires_at > datetime.now(UTC),
                    ),
                )
            )
            session_exists = True
            if source.chat_session_id is not None:
                session_exists = (
                    await db.scalar(
                        select(ChatSession.id).where(
                            ChatSession.id == source.chat_session_id,
                            ChatSession.organization_id == claim.organization_id,
                            ChatSession.user_id == claim.user_id,
                        )
                    )
                    is not None
                )
            if membership is None or not session_exists or source.status != "queued":
                job.status = "cancelled"
                job.completed_at = datetime.now(UTC)
                source.status = "cancelled"
                source.raw_text = None
                await db.commit()
                return
            validated = [MemoryCandidateDTO.model_validate(item) for item in candidates]
            await persist_candidates(db, source, validated)
            job.status = "completed"
            job.completed_at = datetime.now(UTC)
            job.last_error_code = None
            await db.commit()

    async def fail(
        self,
        claim: MemoryJobClaim | dict[str, object],
        error_code: str,
    ) -> None:
        claim = _coerce_claim(claim)
        stable_code = error_code[:100]
        async with self._session_factory() as db:
            job = await db.scalar(
                select(MemoryExtractionJob)
                .where(
                    MemoryExtractionJob.id == claim.job_id,
                    MemoryExtractionJob.organization_id == claim.organization_id,
                    MemoryExtractionJob.user_id == claim.user_id,
                )
                .with_for_update()
            )
            if job is None or job.status != "processing" or job.claimed_by != claim.claimed_by:
                await db.rollback()
                return
            source = await db.scalar(
                select(MemoryCaptureSource)
                .where(
                    MemoryCaptureSource.id == claim.source_id,
                    MemoryCaptureSource.organization_id == claim.organization_id,
                    MemoryCaptureSource.user_id == claim.user_id,
                )
                .with_for_update()
            )
            job.last_error_code = stable_code
            job.claimed_at = None
            job.claimed_by = None
            if job.attempts < job.max_attempts and source is not None:
                job.status = "queued"
                job.available_at = datetime.now(UTC) + self._retry_delay
            else:
                job.status = "failed"
                job.completed_at = datetime.now(UTC)
                if source is not None:
                    source.status = "failed"
            await db.commit()


class MemoryWorker:
    def __init__(
        self,
        *,
        store: MemoryJobStore,
        provider: CandidateProvider,
        worker_id: str,
    ) -> None:
        self.store = store
        self.provider = provider
        self.worker_id = worker_id
        self._stopping = asyncio.Event()
        self._active = 0

    async def run_once(self) -> bool:
        if self._stopping.is_set():
            return False
        claim = await self.store.claim(self.worker_id)
        if claim is None:
            return False
        self._active += 1
        try:
            source_text = _claim_value(claim, "source_text")
            scope_ref = _claim_value(claim, "scope_ref")
            candidates = await self.provider.extract(source_text, scope_ref=scope_ref)
            validated = [MemoryCandidateDTO.model_validate(item) for item in candidates]
            await self.store.complete(claim, validated)
        except TimeoutError:
            await self.store.fail(claim, "provider_timeout")
        except ValidationError:
            await self.store.fail(claim, "provider_invalid_candidate")
        except Exception:
            await self.store.fail(claim, "provider_error")
        finally:
            self._active -= 1
        return True

    async def shutdown(self) -> None:
        self._stopping.set()
        while self._active:
            await asyncio.sleep(0)


async def run_worker(
    worker: MemoryWorker,
    *,
    stop_event: asyncio.Event,
    poll_seconds: float,
) -> None:
    settings = get_settings()
    embedding_provider = build_memory_embedding_provider(settings) if settings.memory_embedding_enabled else None
    embedding_worker_id = f"memory-embedding-worker-{id(stop_event)}"
    while not stop_event.is_set():
        processed = await worker.run_once()
        async with SessionLocal() as db:
            await purge_expired_sources(db)
            await db.commit()
        embedding_processed = 0
        if settings.memory_embedding_enabled:
            embedding_processed = await run_embedding_cycle(
                SessionLocal,
                provider=embedding_provider,
                worker_id=embedding_worker_id,
            )
        if processed or embedding_processed:
            continue
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_seconds)
        except TimeoutError:
            continue
    await worker.shutdown()


async def main(*, stop_event: asyncio.Event | None = None) -> None:
    settings = get_settings()
    resolved_stop_event = stop_event or asyncio.Event()
    if stop_event is None:
        loop = asyncio.get_running_loop()
        for signal_value in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(signal_value, resolved_stop_event.set)
            except NotImplementedError:
                pass
    worker = MemoryWorker(
        store=SqlAlchemyMemoryJobStore(),
        provider=ExtractionProvider(enabled=settings.memory_extraction_enabled),
        worker_id=f"memory-worker-{id(resolved_stop_event)}",
    )
    await run_worker(
        worker,
        stop_event=resolved_stop_event,
        poll_seconds=settings.memory_worker_poll_seconds,
    )


def _claim_value(claim: MemoryJobClaim | dict[str, object], name: str) -> str:
    value = claim.get(name) if isinstance(claim, dict) else getattr(claim, name)
    if not isinstance(value, str):
        raise TypeError(f"claim {name} is invalid")
    return value


def _coerce_claim(claim: MemoryJobClaim | dict[str, object]) -> MemoryJobClaim:
    if isinstance(claim, MemoryJobClaim):
        return claim
    return MemoryJobClaim(
        job_id=int(claim["job_id"]),
        organization_id=int(claim["organization_id"]),
        user_id=int(claim["user_id"]),
        source_id=int(claim["source_id"]),
        source_text=str(claim["source_text"]),
        scope_ref=str(claim["scope_ref"]),
        claimed_by=str(claim["claimed_by"]),
    )


if __name__ == "__main__":
    asyncio.run(main())
