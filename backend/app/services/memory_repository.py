from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    MemoryEmbeddingJob,
    MemoryRecord,
    MemorySourceLink,
    MemoryVersion,
)
from app.services.memory_authorization import owner_active_predicates
from app.services.memory_retrieval import (
    MemoryRetrievalScope,
    retrieve_authorized_memories,
)


class MemoryNotFoundError(KeyError):
    pass


class MemoryRevisionConflictError(RuntimeError):
    pass


class InvalidMemoryCursorError(ValueError):
    pass


@dataclass(frozen=True)
class MemoryPage:
    items: list[MemoryRecord]
    next_cursor: str | None


@dataclass(frozen=True)
class MemoryCandidateItem:
    record: MemoryRecord
    source_ref: str


def encode_cursor(record: MemoryRecord) -> str:
    updated_at = record.updated_at
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    payload = json.dumps(
        [updated_at.isoformat(), record.memory_id],
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError
        timestamp = datetime.fromisoformat(value[0])
        memory_id = value[1]
        if timestamp.tzinfo is None or not isinstance(memory_id, str) or len(memory_id) != 32:
            raise ValueError
        return timestamp, memory_id
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise InvalidMemoryCursorError(cursor) from error


def memory_response_data(record: MemoryRecord) -> dict:
    return {
        "memory_id": record.memory_id,
        "content": record.content,
        "type": record.type,
        "metadata": record.metadata_,
        "revision": record.revision,
        "layer": record.layer,
        "status": record.status,
        "origin": record.origin,
        "source_summary": record.source_summary,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


async def get_active_memory(
    db: AsyncSession,
    memory_id: str,
    *,
    organization_id: int,
    user_id: int,
) -> MemoryRecord:
    record = await db.scalar(
        select(MemoryRecord).where(
            MemoryRecord.memory_id == memory_id,
            *owner_active_predicates(
                organization_id=organization_id,
                user_id=user_id,
            ),
        )
    )
    if record is None:
        raise MemoryNotFoundError(memory_id)
    return record


async def list_active_memories(
    db: AsyncSession,
    *,
    organization_id: int,
    user_id: int,
    query: str,
    memory_type: str | None,
    cursor: str | None,
    limit: int,
) -> MemoryPage:
    decoded_cursor = decode_cursor(cursor) if cursor is not None else None
    if query.strip():
        records = await retrieve_authorized_memories(
            db,
            scope=MemoryRetrievalScope(
                organization_id=organization_id,
                user_id=user_id,
            ),
            query=query,
            limit=100,
            memory_types=(memory_type,) if memory_type is not None else None,
        )
        records.sort(key=lambda item: (item.updated_at, item.memory_id), reverse=True)
        if decoded_cursor is not None:
            records = [
                record
                for record in records
                if (record.updated_at, record.memory_id) < decoded_cursor
            ]
        has_more = len(records) > limit
        items = records[:limit]
        return MemoryPage(
            items=items,
            next_cursor=encode_cursor(items[-1]) if has_more else None,
        )

    statement = select(MemoryRecord).where(
        *owner_active_predicates(
            organization_id=organization_id,
            user_id=user_id,
        )
    )
    if memory_type is not None:
        statement = statement.where(MemoryRecord.type == memory_type)
    if decoded_cursor is not None:
        updated_at, memory_id = decoded_cursor
        statement = statement.where(
            or_(
                MemoryRecord.updated_at < updated_at,
                (
                    (MemoryRecord.updated_at == updated_at)
                    & (MemoryRecord.memory_id < memory_id)
                ),
            )
        )
    records = list(
        (
            await db.scalars(
                statement.order_by(
                    MemoryRecord.updated_at.desc(),
                    MemoryRecord.memory_id.desc(),
                ).limit(limit + 1)
            )
        ).all()
    )
    has_more = len(records) > limit
    items = records[:limit]
    return MemoryPage(
        items=items,
        next_cursor=encode_cursor(items[-1]) if has_more else None,
    )


async def list_candidate_memories(
    db: AsyncSession,
    *,
    organization_id: int,
    user_id: int,
) -> list[MemoryCandidateItem]:
    records = list(
        (
            await db.scalars(
                select(MemoryRecord)
                .where(
                    MemoryRecord.organization_id == organization_id,
                    MemoryRecord.user_id == user_id,
                    MemoryRecord.status == "candidate",
                )
                .order_by(MemoryRecord.created_at, MemoryRecord.memory_id)
            )
        ).all()
    )
    items: list[MemoryCandidateItem] = []
    for record in records:
        source_ref = record.source_summary or "source-unavailable"
        link = await db.scalar(
            select(MemorySourceLink.source_label)
            .where(
                MemorySourceLink.memory_id == record.memory_id,
                MemorySourceLink.organization_id == organization_id,
                MemorySourceLink.user_id == user_id,
            )
            .limit(1)
        )
        if link:
            source_ref = link
        items.append(MemoryCandidateItem(record=record, source_ref=source_ref))
    return items


async def confirm_candidate(
    db: AsyncSession,
    memory_id: str,
    *,
    organization_id: int,
    user_id: int,
    expected_revision: int,
    supersedes_memory_id: str | None = None,
) -> MemoryRecord:
    requested_ids = [memory_id]
    if supersedes_memory_id is not None:
        if supersedes_memory_id == memory_id:
            raise MemoryNotFoundError(supersedes_memory_id)
        requested_ids.append(supersedes_memory_id)
    locked = list(
        (
            await db.scalars(
                select(MemoryRecord)
                .where(
                    MemoryRecord.memory_id.in_(requested_ids),
                    MemoryRecord.organization_id == organization_id,
                    MemoryRecord.user_id == user_id,
                )
                .order_by(MemoryRecord.memory_id)
                .with_for_update()
            )
        ).all()
    )
    by_id = {record.memory_id: record for record in locked}
    record = by_id.get(memory_id)
    if record is None or record.status != "candidate":
        raise MemoryNotFoundError(memory_id)
    if record.revision != expected_revision:
        raise MemoryRevisionConflictError(memory_id)

    now = datetime.now(UTC)
    if supersedes_memory_id is not None:
        superseded = by_id.get(supersedes_memory_id)
        if superseded is None or superseded.status != "active":
            raise MemoryNotFoundError(supersedes_memory_id)
        superseded.status = "superseded"
        superseded.revision += 1
        superseded.updated_at = now
        db.add(_version_from_record(superseded))

    record.status = "active"
    record.revision += 1
    record.updated_at = now
    record.supersedes_memory_id = supersedes_memory_id
    if get_settings().memory_embedding_enabled:
        record.embedding_state = "pending"
    db.add(_version_from_record(record))
    if get_settings().memory_embedding_enabled:
        _enqueue_embedding_job(db, record)
    await db.flush()
    return record


def _enqueue_embedding_job(db: AsyncSession, record: MemoryRecord) -> None:
    db.add(
        MemoryEmbeddingJob(
            organization_id=record.organization_id,
            user_id=record.user_id,
            memory_id=record.memory_id,
            revision=record.revision,
            status="queued",
        )
    )


async def _cancel_stale_embedding_jobs(
    db: AsyncSession,
    *,
    organization_id: int,
    user_id: int,
    memory_id: str,
) -> None:
    # 将未终态 job 置为 cancelled，避免同一记录出现多个可领取 job。
    await db.execute(
        update(MemoryEmbeddingJob)
        .where(
            MemoryEmbeddingJob.organization_id == organization_id,
            MemoryEmbeddingJob.user_id == user_id,
            MemoryEmbeddingJob.memory_id == memory_id,
            MemoryEmbeddingJob.status.in_(["queued", "processing"]),
        )
        .values(status="cancelled")
    )


def _version_from_record(record: MemoryRecord) -> MemoryVersion:
    return MemoryVersion(
        organization_id=record.organization_id,
        user_id=record.user_id,
        memory_id=record.memory_id,
        revision=record.revision,
        content=record.content,
        type=record.type,
        layer=record.layer,
        status=record.status,
        origin=record.origin,
        metadata_=record.metadata_,
        source_summary=record.source_summary,
        confidence=record.confidence,
        provider=record.provider,
        provider_version=record.provider_version,
    )


async def reject_candidate(
    db: AsyncSession,
    memory_id: str,
    *,
    organization_id: int,
    user_id: int,
    expected_revision: int,
) -> None:
    for model in (MemoryEmbeddingJob, MemorySourceLink, MemoryVersion):
        await db.execute(
            delete(model).where(
                model.organization_id == organization_id,
                model.user_id == user_id,
                model.memory_id == memory_id,
            )
        )
    row = (
        await db.execute(
            delete(MemoryRecord)
            .where(
                MemoryRecord.memory_id == memory_id,
                MemoryRecord.organization_id == organization_id,
                MemoryRecord.user_id == user_id,
                MemoryRecord.status == "candidate",
                MemoryRecord.revision == expected_revision,
            )
            .returning(MemoryRecord.memory_id)
        )
    ).one_or_none()
    if row is not None:
        return
    existing = await db.scalar(
        select(MemoryRecord.memory_id).where(
            MemoryRecord.memory_id == memory_id,
            MemoryRecord.organization_id == organization_id,
            MemoryRecord.user_id == user_id,
            MemoryRecord.status == "candidate",
        )
    )
    if existing is None:
        raise MemoryNotFoundError(memory_id)
    raise MemoryRevisionConflictError(memory_id)


async def create_manual_memory(
    db: AsyncSession,
    *,
    organization_id: int,
    user_id: int,
    content: str,
    memory_type: str,
    metadata: dict[str, str],
) -> MemoryRecord:
    now = datetime.now(UTC)
    record = MemoryRecord(
        memory_id=uuid4().hex,
        organization_id=organization_id,
        user_id=user_id,
        content=content,
        type=memory_type,
        layer="L1",
        status="active",
        origin="manual",
        revision=1,
        metadata_=metadata,
        created_at=now,
        updated_at=now,
    )
    if get_settings().memory_embedding_enabled:
        record.embedding_state = "pending"
    db.add(record)
    await db.flush()
    db.add(
        MemoryVersion(
            organization_id=organization_id,
            user_id=user_id,
            memory_id=record.memory_id,
            revision=1,
            content=content,
            type=memory_type,
            layer="L1",
            status="active",
            origin="manual",
            metadata_=metadata,
        )
    )
    if get_settings().memory_embedding_enabled:
        _enqueue_embedding_job(db, record)
    await db.flush()
    await db.refresh(record)
    return record


async def update_active_memory(
    db: AsyncSession,
    memory_id: str,
    *,
    organization_id: int,
    user_id: int,
    content: str,
    expected_revision: int,
) -> MemoryRecord:
    record = await db.scalar(
        update(MemoryRecord)
        .where(
            MemoryRecord.memory_id == memory_id,
            MemoryRecord.revision == expected_revision,
            *owner_active_predicates(
                organization_id=organization_id,
                user_id=user_id,
            ),
        )
        .values(
            content=content,
            revision=MemoryRecord.revision + 1,
            updated_at=datetime.now(UTC),
        )
        .returning(MemoryRecord)
    )
    if record is None:
        existing = await db.scalar(
            select(MemoryRecord.memory_id).where(
                MemoryRecord.memory_id == memory_id,
                *owner_active_predicates(
                    organization_id=organization_id,
                    user_id=user_id,
                ),
            )
        )
        if existing is None:
            raise MemoryNotFoundError(memory_id)
        raise MemoryRevisionConflictError(memory_id)
    db.add(
        MemoryVersion(
            organization_id=record.organization_id,
            user_id=record.user_id,
            memory_id=record.memory_id,
            revision=record.revision,
            content=record.content,
            type=record.type,
            layer=record.layer,
            status=record.status,
            origin=record.origin,
            metadata_=record.metadata_,
            source_summary=record.source_summary,
        )
    )
    # R5 冻结：内容变更后 embedding_state 重置为 pending 并重新 enqueue（master §7.2）。
    # 无既有向量且状态为 not_configured 的记录无需重置，避免无 provider 时空转 job。
    needs_reset = (
        record.embedding_state in {"pending", "ready", "failed"}
        or record.embedding is not None
    )
    if needs_reset:
        record.embedding_state = "pending"
        await _cancel_stale_embedding_jobs(
            db,
            organization_id=record.organization_id,
            user_id=record.user_id,
            memory_id=record.memory_id,
        )
        _enqueue_embedding_job(db, record)
    await db.flush()
    # 变更 + flush 后刷新实例，避免 updated_at 等属性过期导致的提交后懒加载。
    await db.refresh(record)
    return record


async def delete_active_memory(
    db: AsyncSession,
    memory_id: str,
    *,
    organization_id: int,
    user_id: int,
    expected_revision: int,
) -> dict[str, object]:
    for model in (MemoryEmbeddingJob, MemorySourceLink, MemoryVersion):
        await db.execute(
            delete(model).where(
                model.organization_id == organization_id,
                model.user_id == user_id,
                model.memory_id == memory_id,
            )
        )
    row = (
        await db.execute(
            delete(MemoryRecord)
            .where(
                MemoryRecord.memory_id == memory_id,
                MemoryRecord.revision == expected_revision,
                *owner_active_predicates(
                    organization_id=organization_id,
                    user_id=user_id,
                ),
            )
            .returning(
                MemoryRecord.revision,
                MemoryRecord.layer,
                MemoryRecord.origin,
                MemoryRecord.status,
            )
        )
    ).one_or_none()
    if row is None:
        existing = await db.scalar(
            select(MemoryRecord.memory_id).where(
                MemoryRecord.memory_id == memory_id,
                *owner_active_predicates(
                    organization_id=organization_id,
                    user_id=user_id,
                ),
            )
        )
        if existing is None:
            raise MemoryNotFoundError(memory_id)
        raise MemoryRevisionConflictError(memory_id)
    return {
        "revision": row.revision,
        "layer": row.layer,
        "origin": row.origin,
        "status": row.status,
    }
