from __future__ import annotations

import hmac
from hashlib import sha256
from dataclasses import dataclass
from datetime import UTC, datetime
from collections.abc import Sequence
from math import sqrt
from typing import Any, Protocol

from sqlalchemy import func, or_, select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    KnowledgeChunk,
    KnowledgeRetrievalEvent,
    Organization,
    OrganizationMembership,
)
from app.services.knowledge_authorization import (
    AuthorizedKnowledgeEntryRepository,
    AuthorizedKnowledgeSource,
    KnowledgeAuthorizationScope,
)
from app.services.embedding_client import EmbeddingUnavailable
from app.services.query_embedding import QueryEmbeddingClient
from app.schemas.knowledge import KnowledgeRetrieveResponse


@dataclass(frozen=True)
class RetrievalScope:
    organization_id: int
    user_id: int
    membership_id: int | None = None
    member_type: str | None = None


async def record_retrieval_event(
    db: AsyncSession,
    *,
    scope: RetrievalScope,
    query: str,
    request_kind: str,
    retrieval_mode: str,
    result_count: int,
    latency_ms: int,
    outcome: str,
    chat_session_id: int | None = None,
) -> None:
    settings = get_settings()
    if settings.rag_query_audit_hmac_key is None:
        raise RuntimeError("RAG query audit HMAC key is required")
    key = settings.rag_query_audit_hmac_key.get_secret_value().encode()
    digest = hmac.new(key, query.encode(), sha256).hexdigest()
    db.add(
        KnowledgeRetrievalEvent(
            organization_id=scope.organization_id,
            user_id=scope.user_id,
            chat_session_id=chat_session_id,
            query_sha256=None,
            query_hmac=digest,
            query_hmac_version=settings.rag_query_audit_hmac_version,
            request_kind=request_kind,
            retrieval_mode=retrieval_mode,
            result_count=result_count,
            latency_ms=max(0, latency_ms),
            outcome=outcome,
        )
    )


@dataclass(frozen=True)
class RankedChunk:
    chunk_id: int
    score: float


def fuse_ranked_chunks(
    *,
    vector_chunks: list[tuple[int, int]],
    full_text_chunks: list[tuple[int, int]],
    source_by_chunk: dict[int, int],
    k: int = 60,
) -> list[RankedChunk]:
    if k <= 0:
        raise ValueError("k must be positive")
    overlap_sources = {
        source_by_chunk[chunk_id] for _rank, chunk_id in vector_chunks
    } & {source_by_chunk[chunk_id] for _rank, chunk_id in full_text_chunks}
    scores: dict[int, float] = {}
    first_seen: dict[int, int] = {}
    for rank, chunk_id in [*vector_chunks, *full_text_chunks]:
        source = source_by_chunk[chunk_id]
        contribution = 1 / (k + rank)
        if source in overlap_sources:
            contribution *= 1.25
        scores[chunk_id] = scores.get(chunk_id, 0.0) + contribution
        first_seen.setdefault(chunk_id, len(first_seen))
    return [
        RankedChunk(chunk_id=chunk_id, score=score)
        for chunk_id, score in sorted(
            scores.items(), key=lambda item: (-item[1], first_seen[item[0]])
        )
    ]


def apply_adaptive_cutoff(
    ranked: list[RankedChunk], *, relative_score_floor: float = 0.45
) -> list[RankedChunk]:
    if not ranked:
        return []
    if not 0 < relative_score_floor <= 1:
        raise ValueError("relative score floor must be between 0 and 1")
    floor = ranked[0].score * relative_score_floor
    return [item for item in ranked if item.score >= floor]


def diversify_ranked_chunks(
    chunks: list[KnowledgeChunk], *, max_per_source: int
) -> list[tuple[int, int]]:
    if max_per_source <= 0:
        raise ValueError("max_per_source must be positive")
    per_source: dict[int, int] = {}
    diversified: list[int] = []
    for chunk in chunks:
        source_id = chunk.knowledge_entry_id
        if per_source.get(source_id, 0) >= max_per_source:
            continue
        diversified.append(chunk.id)
        per_source[source_id] = per_source.get(source_id, 0) + 1
    return list(enumerate(diversified, start=1))


def fuse_rrf(
    *,
    vector_ids: list[int],
    full_text_ids: list[int],
    k: int = 60,
) -> list[RankedChunk]:
    """Fuse two ranked candidate lists without widening their authorization scope."""
    if k <= 0:
        raise ValueError("k must be positive")

    scores: dict[int, float] = {}
    first_seen: dict[int, int] = {}
    for rank, chunk_id in enumerate(vector_ids, start=1):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1 / (k + rank)
        first_seen.setdefault(chunk_id, len(first_seen))
    for rank, chunk_id in enumerate(full_text_ids, start=1):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1 / (k + rank)
        first_seen.setdefault(chunk_id, len(first_seen))
    return [
        RankedChunk(chunk_id=chunk_id, score=score)
        for chunk_id, score in sorted(
            scores.items(), key=lambda item: (-item[1], first_seen[item[0]])
        )
    ]


class AuthorizedSourceRepository(Protocol):
    async def authorized_sources(
        self,
        scope: RetrievalScope,
        source_ids: list[int],
    ) -> list[AuthorizedKnowledgeSource]: ...


class CandidateRetriever(Protocol):
    async def retrieve(
        self,
        query: str,
        sources: list[AuthorizedKnowledgeSource],
        limit: int,
    ) -> KnowledgeRetrieveResponse: ...


class QueryEmbeddingProvider(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class SqlAlchemyAuthorizedSourceRepository:
    """Resolves current visible ready revisions through the shared authorization repository."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def authorized_sources(
        self,
        scope: RetrievalScope,
        source_ids: list[int],
    ) -> list[AuthorizedKnowledgeSource]:
        membership_id = scope.membership_id
        member_type = scope.member_type
        if membership_id is None or member_type is None:
            membership = await self._db.scalar(
                select(OrganizationMembership)
                .join(Organization, Organization.id == OrganizationMembership.organization_id)
                .where(
                    OrganizationMembership.organization_id == scope.organization_id,
                    OrganizationMembership.user_id == scope.user_id,
                    OrganizationMembership.is_active.is_(True),
                    Organization.is_active.is_(True),
                    or_(
                        OrganizationMembership.expires_at.is_(None),
                        OrganizationMembership.expires_at > datetime.now(UTC),
                    ),
                )
            )
            if membership is None:
                return []
            membership_id = membership.id
            member_type = membership.member_type
        repository = AuthorizedKnowledgeEntryRepository(
            self._db,
            KnowledgeAuthorizationScope(
                organization_id=scope.organization_id,
                user_id=scope.user_id,
                membership_id=membership_id,
                member_type=member_type,
            ),
        )
        return await repository.authorized_sources(source_ids)


class PlatformPgVectorCandidateRetriever:
    """Performs vector and full-text retrieval after authorization has completed."""

    VECTOR_LIMIT = 24
    FULL_TEXT_LIMIT = 24
    MAX_PER_SOURCE = 1
    MAX_CONTEXT_CHARACTERS = 12_000
    RELATIVE_SCORE_FLOOR = 0.9

    def __init__(
        self,
        db: AsyncSession,
        *,
        embedding_client: QueryEmbeddingProvider | None,
    ) -> None:
        self._db = db
        self._embedding_client = embedding_client

    async def retrieve(
        self,
        query: str,
        sources: list[AuthorizedKnowledgeSource],
        limit: int,
    ) -> KnowledgeRetrieveResponse:
        source_by_id = {source.entry_id: source for source in sources}
        organization_ids = {source.organization_id for source in sources}
        if len(organization_ids) != 1 or None in organization_ids:
            raise ValueError("authorized sources must carry one organization scope")
        if any(source.user_id is None for source in sources):
            raise ValueError("authorized sources must carry owner identity")
        organization_id = next(iter(organization_ids))
        assert organization_id is not None
        allowed_ids = list(source_by_id)
        allowed_revisions = [
            (source.entry_id, source.user_id, source.content_sha256)
            for source in sources
        ]
        full_text = await self._full_text_candidates(
            query=query,
            organization_id=organization_id,
            user_id=0,
            allowed_ids=allowed_ids,
            allowed_revisions=allowed_revisions,
        )

        mode = "hybrid"
        vector: list[KnowledgeChunk] = []
        try:
            vector = await self._vector_candidates(
                query=query,
                organization_id=organization_id,
                user_id=0,
                allowed_ids=allowed_ids,
                allowed_revisions=allowed_revisions,
            )
        except (EmbeddingUnavailable, RuntimeError, ValueError):
            mode = "degraded_full_text"

        chunk_by_id = {chunk.id: chunk for chunk in [*vector, *full_text]}
        source_by_chunk = {
            chunk.id: chunk.knowledge_entry_id for chunk in [*vector, *full_text]
        }
        fused = apply_adaptive_cutoff(
            fuse_ranked_chunks(
                vector_chunks=diversify_ranked_chunks(
                    vector, max_per_source=self.MAX_PER_SOURCE
                ),
                full_text_chunks=diversify_ranked_chunks(
                    full_text, max_per_source=self.MAX_PER_SOURCE
                ),
                source_by_chunk=source_by_chunk,
            ),
            relative_score_floor=self.RELATIVE_SCORE_FLOOR,
        )
        per_source: dict[int, int] = {}
        remaining_characters = self.MAX_CONTEXT_CHARACTERS
        citations = []
        for ranked in fused:
            chunk = chunk_by_id[ranked.chunk_id]
            source = source_by_id.get(chunk.knowledge_entry_id)
            if source is None or per_source.get(source.entry_id, 0) >= self.MAX_PER_SOURCE:
                continue
            if remaining_characters <= 0:
                break
            text = chunk.text[:remaining_characters]
            if not text:
                continue
            citations.append(
                {
                    "entry_id": source.entry_id,
                    "title": source.title,
                    "content_sha256": source.content_sha256,
                    "source_locator": chunk.source_locator,
                    "text": text,
                    "score": ranked.score,
                }
            )
            per_source[source.entry_id] = per_source.get(source.entry_id, 0) + 1
            remaining_characters -= len(text)
            if len(citations) >= limit:
                break
        return KnowledgeRetrieveResponse(citations=citations, mode=mode)

    def _scoped_chunks_statement(
        self,
        *,
        organization_id: int,
        user_id: int,
        allowed_ids: list[int],
        allowed_revisions: list[tuple[int, int | None, str]],
    ):
        # The scope predicates are deliberately repeated for every candidate query.
        return (
            select(KnowledgeChunk)
            .where(
                KnowledgeChunk.organization_id == organization_id,
                KnowledgeChunk.knowledge_entry_id.in_(allowed_ids),
                tuple_(
                    KnowledgeChunk.knowledge_entry_id,
                    KnowledgeChunk.user_id,
                    KnowledgeChunk.content_sha256,
                ).in_(allowed_revisions),
            )
        )

    async def _vector_candidates(
        self,
        *,
        query: str,
        organization_id: int,
        user_id: int,
        allowed_ids: list[int],
        allowed_revisions: list[tuple[int, int | None, str]],
    ) -> list[KnowledgeChunk]:
        if self._embedding_client is None:
            raise EmbeddingUnavailable("embedding_unavailable")
        vectors = await self._embedding_client.embed([query])
        if len(vectors) != 1:
            raise EmbeddingUnavailable("embedding_unavailable")
        vector = vectors[0]
        if self._db.get_bind().dialect.name == "postgresql":
            distance = KnowledgeChunk.embedding.cosine_distance(vector)
            statement = (
                self._scoped_chunks_statement(
                    allowed_ids=allowed_ids,
                    allowed_revisions=allowed_revisions,
                    organization_id=organization_id,
                    user_id=user_id,
                )
                .order_by(distance)
                .limit(self.VECTOR_LIMIT)
            )
            return list((await self._db.scalars(statement)).all())[: self.VECTOR_LIMIT]

        chunks = list(
            (
                await self._db.scalars(
                    self._scoped_chunks_statement(
                        allowed_ids=allowed_ids,
                        allowed_revisions=allowed_revisions,
                        organization_id=organization_id,
                        user_id=user_id,
                    ).limit(self.VECTOR_LIMIT)
                )
            ).all()
        )
        return sorted(
            chunks,
            key=lambda chunk: self._cosine_distance(vector, chunk.embedding),
        )[: self.VECTOR_LIMIT]

    async def _full_text_candidates(
        self,
        *,
        query: str,
        organization_id: int,
        user_id: int,
        allowed_ids: list[int],
        allowed_revisions: list[tuple[int, int | None, str]],
    ) -> list[KnowledgeChunk]:
        if self._db.get_bind().dialect.name == "postgresql":
            statement = self._full_text_statement(
                query=query,
                organization_id=organization_id,
                user_id=user_id,
                allowed_ids=allowed_ids,
                allowed_revisions=allowed_revisions,
                coarse_limit=self.FULL_TEXT_LIMIT * 8,
            )
            await self._db.execute(text("SET LOCAL enable_seqscan = off"))
            chunks = list((await self._db.scalars(statement)).all())
            await self._db.execute(text("SET LOCAL enable_seqscan = on"))
            return chunks

        statement = self._scoped_chunks_statement(
            allowed_ids=allowed_ids,
            allowed_revisions=allowed_revisions,
            organization_id=organization_id,
            user_id=user_id,
        )
        terms = [term for term in query.casefold().split() if term]
        if not terms:
            return []
        statement = statement.where(
            or_(*(KnowledgeChunk.text.ilike(f"%{term}%") for term in terms))
        ).limit(self.FULL_TEXT_LIMIT)
        chunks = list((await self._db.scalars(statement)).all())
        ranked = [
            (sum(chunk.text.casefold().count(term) for term in terms), chunk)
            for chunk in chunks
        ]
        ordered = sorted(ranked, key=lambda item: (-item[0], item[1].id))
        return [chunk for score, chunk in ordered if score][: self.FULL_TEXT_LIMIT]

    def _full_text_statement(
        self,
        *,
        query: str,
        organization_id: int,
        user_id: int,
        allowed_ids: list[int],
        allowed_revisions: list[tuple[int, int | None, str]],
        coarse_limit: int,
    ):
        scope = self._scoped_chunks_statement(
            allowed_ids=allowed_ids,
            allowed_revisions=allowed_revisions,
            organization_id=organization_id,
            user_id=user_id,
        )
        query_cte = select(func.plainto_tsquery("simple", query).label("query_vector")).cte(
            "search_query"
        )
        document_vector = func.to_tsvector("simple", KnowledgeChunk.text)
        rank = func.ts_rank_cd(document_vector, query_cte.c.query_vector)
        return (
            scope.select_from(KnowledgeChunk, query_cte)
            .where(document_vector.op("@@")(query_cte.c.query_vector))
            .order_by(rank.desc(), KnowledgeChunk.id)
            .limit(coarse_limit)
        )

    @staticmethod
    def _cosine_distance(left: list[float], right: Any) -> float:
        if not isinstance(right, list) or len(left) != len(right):
            raise EmbeddingUnavailable("embedding_unavailable")
        denominator = sqrt(sum(value * value for value in left)) * sqrt(
            sum(value * value for value in right)
        )
        if denominator == 0:
            raise EmbeddingUnavailable("embedding_unavailable")
        numerator = sum(
            first * second for first, second in zip(left, right, strict=True)
        )
        return 1 - numerator / denominator


class KnowledgeRetriever:
    def __init__(
        self,
        *,
        repository: AuthorizedSourceRepository,
        candidates: CandidateRetriever,
    ) -> None:
        self.repository = repository
        self.candidates = candidates

    async def retrieve(
        self,
        *,
        scope: RetrievalScope,
        query: str,
        source_ids: list[int],
        limit: int = 8,
    ) -> KnowledgeRetrieveResponse:
        response, _rejected_source_count = await self.retrieve_with_metadata(
            scope=scope,
            query=query,
            source_ids=source_ids,
            limit=limit,
        )
        return response

    async def retrieve_with_metadata(
        self,
        *,
        scope: RetrievalScope,
        query: str,
        source_ids: list[int],
        limit: int = 8,
    ) -> tuple[KnowledgeRetrieveResponse, int]:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("query must not be empty")
        if not 1 <= limit <= 8:
            raise ValueError("limit must be between 1 and 8")

        authorized = await self.repository.authorized_sources(scope, source_ids)
        rejected_source_count = (
            len(set(source_ids)) - len({source.entry_id for source in authorized})
            if source_ids
            else 0
        )
        if not authorized:
            return KnowledgeRetrieveResponse(citations=[], mode="empty"), rejected_source_count
        response = await self.candidates.retrieve(normalized_query, authorized, limit)
        return response, rejected_source_count


def build_platform_knowledge_retriever(db: AsyncSession) -> KnowledgeRetriever:
    settings = get_settings()
    embedding_client = None
    if (
        settings.rag_embedding_enabled
        and settings.rag_query_embedding_url
        and settings.rag_query_embedding_token
    ):
        embedding_client = QueryEmbeddingClient(
            base_url=settings.rag_query_embedding_url,
            auth_token=settings.rag_query_embedding_token,
            timeout_seconds=settings.rag_query_embedding_timeout_seconds,
        )
    return KnowledgeRetriever(
        repository=SqlAlchemyAuthorizedSourceRepository(db),
        candidates=PlatformPgVectorCandidateRetriever(
            db,
            embedding_client=embedding_client,
        ),
    )
