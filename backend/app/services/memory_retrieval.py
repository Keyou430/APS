from __future__ import annotations

import hashlib
import hmac
from collections.abc import Sequence
from dataclasses import dataclass
from math import sqrt
from typing import Any, Protocol

from sqlalchemy import func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.config import get_settings
from app.models import MemoryRecord, MemoryRetrievalEvent
from app.services.embedding_client import EmbeddingUnavailable


@dataclass(frozen=True)
class MemoryRetrievalScope:
    organization_id: int
    user_id: int


@dataclass(frozen=True)
class RankedMemory:
    memory_id: str
    score: float


class MemoryEmbeddingProvider(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def _active_scope_predicates(
    scope: MemoryRetrievalScope,
    *,
    memory_types: Sequence[str] | None = None,
    layers: Sequence[str] | None = None,
) -> list[Any]:
    predicates: list[Any] = [
        MemoryRecord.organization_id == scope.organization_id,
        MemoryRecord.user_id == scope.user_id,
        MemoryRecord.status == "active",
    ]
    if memory_types:
        predicates.append(MemoryRecord.type.in_(tuple(memory_types)))
    if layers:
        predicates.append(MemoryRecord.layer.in_(tuple(layers)))
    return predicates


def build_memory_fts_statement(
    *,
    scope: MemoryRetrievalScope,
    query: str,
    limit: int,
    memory_types: Sequence[str] | None = None,
    layers: Sequence[str] | None = None,
) -> Select:
    text_search_config = literal_column("'simple'")
    query_vector = func.websearch_to_tsquery(text_search_config, query)
    document_vector = func.to_tsvector(text_search_config, MemoryRecord.content)
    rank = func.ts_rank_cd(document_vector, query_vector)
    return (
        select(MemoryRecord)
        .where(
            *_active_scope_predicates(
                scope,
                memory_types=memory_types,
                layers=layers,
            ),
            document_vector.op("@@")(query_vector),
        )
        .order_by(rank.desc(), MemoryRecord.updated_at.desc(), MemoryRecord.memory_id.desc())
        .limit(limit)
    )


def build_memory_vector_statement(
    *,
    scope: MemoryRetrievalScope,
    vector: Sequence[float],
    limit: int,
    memory_types: Sequence[str] | None = None,
    layers: Sequence[str] | None = None,
) -> Select:
    distance = MemoryRecord.embedding.cosine_distance(list(vector))
    return (
        select(MemoryRecord)
        .where(
            *_active_scope_predicates(
                scope,
                memory_types=memory_types,
                layers=layers,
            ),
            MemoryRecord.embedding.is_not(None),
            MemoryRecord.embedding_state == "ready",
        )
        .order_by(distance)
        .limit(limit)
    )


def fuse_memory_rrf(
    *,
    vector_ids: Sequence[str],
    full_text_ids: Sequence[str],
    k: int = 60,
) -> list[RankedMemory]:
    if k <= 0:
        raise ValueError("k must be positive")
    scores: dict[str, float] = {}
    for ids in (vector_ids, full_text_ids):
        for rank, memory_id in enumerate(ids, start=1):
            scores[memory_id] = scores.get(memory_id, 0.0) + 1 / (k + rank)
    return [
        RankedMemory(memory_id=memory_id, score=score)
        for memory_id, score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    ]


async def record_memory_retrieval_event(
    db: AsyncSession,
    *,
    scope: MemoryRetrievalScope,
    query: str,
    memory_mode: str,
    result_count: int,
    latency_ms: int,
    outcome: str,
    retrieval_mode: str,
    chat_session_id: int | None = None,
) -> None:
    settings = get_settings()
    if settings.rag_query_audit_hmac_key is None:
        raise RuntimeError("RAG query audit HMAC key is required")
    digest = hmac.new(
        settings.rag_query_audit_hmac_key.get_secret_value().encode(),
        query.encode(),
        hashlib.sha256,
    ).hexdigest()
    db.add(
        MemoryRetrievalEvent(
            organization_id=scope.organization_id,
            user_id=scope.user_id,
            chat_session_id=chat_session_id,
            query_hmac=digest,
            query_hmac_version=settings.rag_query_audit_hmac_version,
            memory_mode=memory_mode,
            retrieval_mode=retrieval_mode,
            result_count=result_count,
            latency_ms=max(0, latency_ms),
            outcome=outcome,
        )
    )


async def retrieve_authorized_memories(
    db: AsyncSession,
    *,
    scope: MemoryRetrievalScope,
    query: str,
    limit: int = 10,
    memory_types: Sequence[str] | None = None,
    layers: Sequence[str] | None = None,
    embedding_provider: MemoryEmbeddingProvider | None = None,
    overfetch: int = 4,
) -> list[MemoryRecord]:
    if limit <= 0 or overfetch <= 0:
        raise ValueError("retrieval limits must be positive")
    normalized = query.strip()
    if not normalized:
        return list(
            (
                await db.scalars(
                    select(MemoryRecord)
                    .where(
                        *_active_scope_predicates(
                            scope,
                            memory_types=memory_types,
                            layers=layers,
                        )
                    )
                    .order_by(MemoryRecord.updated_at.desc(), MemoryRecord.memory_id.desc())
                    .limit(limit)
                )
            ).all()
        )

    candidate_limit = min(100, limit * overfetch)
    if db.get_bind().dialect.name == "postgresql":
        full_text = list(
            (
                await db.scalars(
                    build_memory_fts_statement(
                        scope=scope,
                        query=normalized,
                        limit=candidate_limit,
                        memory_types=memory_types,
                        layers=layers,
                    )
                )
            ).all()
        )
    else:
        full_text = await _sqlite_full_text_candidates(
            db,
            scope=scope,
            query=normalized,
            limit=candidate_limit,
            memory_types=memory_types,
            layers=layers,
        )

    vector_records: list[MemoryRecord] = []
    if embedding_provider is not None:
        try:
            vectors = await embedding_provider.embed([normalized])
            if len(vectors) != 1 or len(vectors[0]) != 1024:
                raise EmbeddingUnavailable("embedding_unavailable")
            if db.get_bind().dialect.name == "postgresql":
                ann_records = list(
                    (
                        await db.scalars(
                            build_memory_vector_statement(
                                scope=scope,
                                vector=vectors[0],
                                limit=candidate_limit,
                                memory_types=memory_types,
                                layers=layers,
                            )
                        )
                    ).all()
                )
                exact_records = await _bounded_exact_vector_candidates(
                    db,
                    scope=scope,
                    vector=vectors[0],
                    limit=candidate_limit,
                    memory_types=memory_types,
                    layers=layers,
                )
                vector_records = list(
                    {
                        record.memory_id: record
                        for record in [*ann_records, *exact_records]
                    }.values()
                )
            else:
                vector_records = await _sqlite_vector_candidates(
                    db,
                    scope=scope,
                    vector=vectors[0],
                    limit=candidate_limit,
                    memory_types=memory_types,
                    layers=layers,
                )
        except EmbeddingUnavailable:
            vector_records = []

    by_id = {record.memory_id: record for record in [*full_text, *vector_records]}
    ranked = fuse_memory_rrf(
        vector_ids=[record.memory_id for record in vector_records],
        full_text_ids=[record.memory_id for record in full_text],
    )
    return [by_id[item.memory_id] for item in ranked[:limit]]


async def _sqlite_full_text_candidates(
    db: AsyncSession,
    *,
    scope: MemoryRetrievalScope,
    query: str,
    limit: int,
    memory_types: Sequence[str] | None,
    layers: Sequence[str] | None,
) -> list[MemoryRecord]:
    terms = [term for term in query.casefold().split() if term]
    if not terms:
        return []
    records = list(
        (
            await db.scalars(
                select(MemoryRecord)
                .where(
                    *_active_scope_predicates(
                        scope,
                        memory_types=memory_types,
                        layers=layers,
                    ),
                    or_(*(MemoryRecord.content.ilike(f"%{term}%") for term in terms)),
                )
                .limit(limit)
            )
        ).all()
    )
    return sorted(
        records,
        key=lambda record: (
            -sum(record.content.casefold().count(term) for term in terms),
            record.memory_id,
        ),
    )


async def _sqlite_vector_candidates(
    db: AsyncSession,
    *,
    scope: MemoryRetrievalScope,
    vector: list[float],
    limit: int,
    memory_types: Sequence[str] | None,
    layers: Sequence[str] | None,
) -> list[MemoryRecord]:
    records = list(
        (
            await db.scalars(
                select(MemoryRecord).where(
                    *_active_scope_predicates(
                        scope,
                        memory_types=memory_types,
                        layers=layers,
                    ),
                    MemoryRecord.embedding.is_not(None),
                    MemoryRecord.embedding_state == "ready",
                )
            )
        ).all()
    )
    return sorted(
        records,
        key=lambda record: (_cosine_distance(vector, record.embedding), record.memory_id),
    )[:limit]


async def _bounded_exact_vector_candidates(
    db: AsyncSession,
    *,
    scope: MemoryRetrievalScope,
    vector: list[float],
    limit: int,
    memory_types: Sequence[str] | None,
    layers: Sequence[str] | None,
) -> list[MemoryRecord]:
    records = list(
        (
            await db.scalars(
                select(MemoryRecord)
                .where(
                    *_active_scope_predicates(
                        scope,
                        memory_types=memory_types,
                        layers=layers,
                    ),
                    MemoryRecord.embedding.is_not(None),
                    MemoryRecord.embedding_state == "ready",
                )
                .order_by(MemoryRecord.updated_at.desc(), MemoryRecord.memory_id.desc())
                .limit(100)
            )
        ).all()
    )
    return sorted(
        records,
        key=lambda record: (_cosine_distance(vector, record.embedding), record.memory_id),
    )[:limit]


def _cosine_distance(left: list[float], right: Any) -> float:
    if not isinstance(right, list) or len(left) != len(right):
        raise EmbeddingUnavailable("embedding_unavailable")
    denominator = sqrt(sum(value * value for value in left)) * sqrt(
        sum(value * value for value in right)
    )
    if denominator == 0:
        raise EmbeddingUnavailable("embedding_unavailable")
    return 1 - sum(a * b for a, b in zip(left, right, strict=True)) / denominator
