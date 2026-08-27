from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from hashlib import sha256
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Any, Protocol

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KnowledgeChunk, KnowledgeEntry, KnowledgeIngestionJob
from app.services.document_parser import chunk_text
from app.services.embedding_client import EmbeddingInvalidDimension, EmbeddingUnavailable
from app.services.object_storage import ObjectStorage


PARSER_VERSION = "docling-v1"
EMBEDDING_MODEL = "text-embedding-v4"
EMBEDDING_DIMENSION = 1024
MAX_ATTEMPTS = 3
_sqlite_claim_lock = asyncio.Lock()


class EmbeddingProvider(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class EmptyDocument(RuntimeError):
    pass


def queued_job_claim_statement(dialect_name: str):
    statement = (
        select(KnowledgeIngestionJob)
        .where(
            KnowledgeIngestionJob.status == "queued",
            KnowledgeIngestionJob.attempts < MAX_ATTEMPTS,
        )
        .order_by(KnowledgeIngestionJob.created_at, KnowledgeIngestionJob.id)
        .limit(1)
    )
    if dialect_name == "postgresql":
        return statement.with_for_update(skip_locked=True)
    return statement


async def _claim_next_job_unlocked(db: AsyncSession) -> KnowledgeIngestionJob | None:
    dialect_name = db.get_bind().dialect.name
    job = await db.scalar(queued_job_claim_statement(dialect_name))
    if job is None:
        return None
    job.status = "processing"
    job.attempts += 1
    job.last_error_code = None
    await db.commit()
    await db.refresh(job)
    return job


async def claim_next_job(db: AsyncSession) -> KnowledgeIngestionJob | None:
    if db.get_bind().dialect.name == "sqlite":
        async with _sqlite_claim_lock:
            return await _claim_next_job_unlocked(db)
    return await _claim_next_job_unlocked(db)


def active_ingestion_cancel_statement(dialect_name: str, entry_id: int):
    statement = select(KnowledgeIngestionJob).where(
        KnowledgeIngestionJob.knowledge_entry_id == entry_id,
        KnowledgeIngestionJob.status.in_(("queued", "processing")),
    )
    if dialect_name == "postgresql":
        return statement.with_for_update()
    return statement


async def cancel_active_ingestions(db: AsyncSession, entry_id: int) -> None:
    statement = active_ingestion_cancel_statement(db.get_bind().dialect.name, entry_id)
    jobs = list((await db.scalars(statement)).all())
    for job in jobs:
        job.status = "cancelled"
    await db.flush()


async def entry_content_sha256(entry: KnowledgeEntry, storage: ObjectStorage) -> str:
    if entry.type == "file" and entry.file_path:
        content = await storage.open_read(entry.file_path)
    else:
        content = (entry.content or "").encode("utf-8")
    return sha256(content).hexdigest()


async def enqueue_ingestion(
    db: AsyncSession,
    entry: KnowledgeEntry,
    storage: ObjectStorage,
) -> KnowledgeIngestionJob:
    content_sha256 = await entry_content_sha256(entry, storage)
    existing = await db.scalar(
        select(KnowledgeIngestionJob).where(
            KnowledgeIngestionJob.knowledge_entry_id == entry.id,
            KnowledgeIngestionJob.content_sha256 == content_sha256,
        )
    )
    if existing is not None:
        return existing

    job = KnowledgeIngestionJob(
        organization_id=entry.organization_id,
        user_id=entry.user_id,
        knowledge_entry_id=entry.id,
        content_sha256=content_sha256,
        status="queued",
        attempts=0,
        parser_version=PARSER_VERSION,
        embedding_model=EMBEDDING_MODEL,
        embedding_dimension=EMBEDDING_DIMENSION,
    )
    db.add(job)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await db.scalar(
            select(KnowledgeIngestionJob).where(
                KnowledgeIngestionJob.knowledge_entry_id == entry.id,
                KnowledgeIngestionJob.content_sha256 == content_sha256,
            )
        )
        if existing is None:
            raise
        return existing
    await db.refresh(job)
    return job


class KnowledgeIngestionProcessor:
    def __init__(
        self,
        session_factory: Callable[[], Any],
        *,
        storage: ObjectStorage,
        parser: Any,
        embedding_client: EmbeddingProvider,
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage
        self._parser = parser
        self._embedding_client = embedding_client

    async def process_next(self) -> bool:
        async with self._session_factory() as claim_db:
            claimed = await claim_next_job(claim_db)
        if claimed is None:
            return False

        try:
            await self._process_claimed(claimed.id)
        except Exception as exc:
            await self._record_failure(claimed.id, self._stable_error_code(exc))
        return True

    async def _process_claimed(self, job_id: int) -> None:
        async with self._session_factory() as db:
            job = await db.get(KnowledgeIngestionJob, job_id)
            if job is None or job.status != "processing":
                return
            entry = await db.get(KnowledgeEntry, job.knowledge_entry_id)
            if entry is None:
                return
            text = await self._load_entry_text(entry)
            chunks = chunk_text(text)
            if not chunks:
                raise EmptyDocument("empty_document")
            vectors = await self._embedding_client.embed([chunk.text for chunk in chunks])
            if len(vectors) != len(chunks):
                raise RuntimeError("embedding_unavailable")

            job = await db.scalar(
                select(KnowledgeIngestionJob)
                .where(KnowledgeIngestionJob.id == job_id)
                .with_for_update()
            )
            if job is None:
                return
            if job.status == "cancel_requested":
                job.status = "cancelled"
                await db.commit()
                return
            if job.status != "processing":
                return
            await db.refresh(entry)
            if entry.archived_at is not None:
                job.status = "cancelled"
                await db.commit()
                return

            db.add_all(
                [
                    KnowledgeChunk(
                        organization_id=job.organization_id,
                        user_id=job.user_id,
                        knowledge_entry_id=job.knowledge_entry_id,
                        content_sha256=job.content_sha256,
                        ordinal=chunk.ordinal,
                        text=chunk.text,
                        text_sha256=sha256(chunk.text.encode("utf-8")).hexdigest(),
                        source_locator=f"chunk:{chunk.ordinal}",
                        embedding=vector,
                    )
                    for chunk, vector in zip(chunks, vectors, strict=True)
                ]
            )
            await db.flush()
            await db.execute(
                delete(KnowledgeChunk).where(
                    KnowledgeChunk.knowledge_entry_id == job.knowledge_entry_id,
                    KnowledgeChunk.content_sha256 != job.content_sha256,
                )
            )
            job.status = "ready"
            job.last_error_code = None
            await db.commit()

    async def _load_entry_text(self, entry: KnowledgeEntry) -> str:
        if entry.type != "file":
            return entry.content or ""
        if not entry.file_path:
            raise RuntimeError("source_unavailable")
        content = await self._storage.open_read(entry.file_path)
        suffix = PurePosixPath(entry.file_path.replace("\\", "/")).suffix.lower()
        with TemporaryDirectory(prefix="knowledge-ingestion-") as temporary_directory:
            source_path = Path(temporary_directory) / f"source{suffix}"
            await asyncio.to_thread(source_path.write_bytes, content)
            parsed = await asyncio.to_thread(self._parser.parse, source_path)
            return parsed.markdown

    async def _record_failure(self, job_id: int, error_code: str) -> None:
        async with self._session_factory() as db:
            job = await db.get(KnowledgeIngestionJob, job_id)
            if job is None:
                return
            if job.status == "cancel_requested":
                job.status = "cancelled"
                job.last_error_code = None
                await db.commit()
                return
            if job.status != "processing":
                return
            job.status = "failed" if job.attempts >= MAX_ATTEMPTS else "queued"
            job.last_error_code = error_code
            await db.commit()

    @staticmethod
    def _stable_error_code(exc: Exception) -> str:
        if isinstance(exc, EmptyDocument):
            return "empty_document"
        if isinstance(exc, EmbeddingInvalidDimension):
            return "embedding_invalid_dimension"
        if isinstance(exc, EmbeddingUnavailable):
            return "embedding_unavailable"
        return "ingestion_failed"
