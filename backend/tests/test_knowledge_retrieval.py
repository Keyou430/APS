from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy.dialects import postgresql

from app.database import SessionLocal
from app.models import KnowledgeChunk, KnowledgeEntry, KnowledgeIngestionJob
from app.schemas.knowledge import KnowledgeCitation, KnowledgeRetrieveResponse
from app.services.knowledge_retrieval import (
    AuthorizedKnowledgeSource,
    KnowledgeRetriever,
    PlatformPgVectorCandidateRetriever,
    RankedChunk,
    RetrievalScope,
    fuse_rrf,
    apply_adaptive_cutoff,
    diversify_ranked_chunks,
    fuse_ranked_chunks,
)


@dataclass
class RecordingRepository:
    visible_sources: list[AuthorizedKnowledgeSource]
    calls: list[tuple[RetrievalScope, list[int]]] = field(default_factory=list)

    async def authorized_sources(
        self,
        scope: RetrievalScope,
        source_ids: list[int],
    ) -> list[AuthorizedKnowledgeSource]:
        self.calls.append((scope, source_ids))
        return self.visible_sources


@dataclass
class RecordingCandidates:
    result: KnowledgeRetrieveResponse
    calls: list[tuple[str, list[AuthorizedKnowledgeSource], int]] = field(default_factory=list)

    async def retrieve(
        self,
        query: str,
        sources: list[AuthorizedKnowledgeSource],
        limit: int,
    ) -> KnowledgeRetrieveResponse:
        self.calls.append((query, sources, limit))
        return self.result


@pytest.mark.asyncio
async def test_retrieve_rejects_foreign_source_before_candidate_search() -> None:
    repository = RecordingRepository(visible_sources=[])
    candidates = RecordingCandidates(
        result=KnowledgeRetrieveResponse(citations=[], mode="hybrid")
    )
    retriever = KnowledgeRetriever(repository=repository, candidates=candidates)
    scope = RetrievalScope(organization_id=1, user_id=10)

    result = await retriever.retrieve(
        scope=scope,
        query="年度制度",
        source_ids=[20],
    )

    assert result == KnowledgeRetrieveResponse(citations=[], mode="empty")
    assert repository.calls == [(scope, [20])]
    assert candidates.calls == []


@pytest.mark.asyncio
async def test_retrieve_passes_only_repository_authorized_sources_to_candidates() -> None:
    source = AuthorizedKnowledgeSource(
        entry_id=11,
        title="员工制度",
        content_sha256="a" * 64,
        source_locator="page:2",
    )
    citation = KnowledgeCitation(
        entry_id=11,
        title="员工制度",
        content_sha256="a" * 64,
        source_locator="page:2",
        text="年假按制度执行。",
        score=0.91,
    )
    repository = RecordingRepository(visible_sources=[source])
    expected = KnowledgeRetrieveResponse(citations=[citation], mode="hybrid")
    candidates = RecordingCandidates(result=expected)
    retriever = KnowledgeRetriever(repository=repository, candidates=candidates)

    result = await retriever.retrieve(
        scope=RetrievalScope(organization_id=1, user_id=10),
        query="年假",
        source_ids=[11, 20],
        limit=8,
    )

    assert result == expected
    assert candidates.calls == [("年假", [source], 8)]


def test_rrf_prefers_items_returned_by_both_retrievers() -> None:
    merged = fuse_rrf(vector_ids=[1, 2], full_text_ids=[2, 3], k=60)

    assert [item.chunk_id for item in merged] == [2, 1, 3]


def test_rrf_rejects_non_positive_k() -> None:
    with pytest.raises(ValueError, match="k must be positive"):
        fuse_rrf(vector_ids=[1], full_text_ids=[], k=0)


def test_source_overlap_gets_a_deterministic_fusion_boost() -> None:
    ranked = fuse_ranked_chunks(
        vector_chunks=[(1, 10), (2, 20)],
        full_text_chunks=[(2, 20), (3, 30)],
        source_by_chunk={10: 100, 20: 200, 30: 300},
    )

    assert [item.chunk_id for item in ranked] == [20, 10, 30]
    assert ranked[0].score > ranked[1].score


def test_adaptive_cutoff_keeps_relevant_score_band_without_filling_limit() -> None:
    ranked = [
        RankedChunk(chunk_id=1, score=1.0),
        RankedChunk(chunk_id=2, score=0.72),
        RankedChunk(chunk_id=3, score=0.2),
    ]

    assert [item.chunk_id for item in apply_adaptive_cutoff(ranked)] == [1, 2]


def test_adaptive_cutoff_is_not_a_fixed_one_result_limit() -> None:
    ranked = [
        RankedChunk(chunk_id=1, score=1.0),
        RankedChunk(chunk_id=2, score=0.96),
        RankedChunk(chunk_id=3, score=0.91),
        RankedChunk(chunk_id=4, score=0.2),
    ]
    assert [item.chunk_id for item in apply_adaptive_cutoff(ranked, relative_score_floor=0.9)] == [1, 2, 3]


def test_candidate_ranks_are_rebased_after_source_diversification() -> None:
    chunks = [
        SimpleNamespace(id=chunk_id, knowledge_entry_id=100)
        for chunk_id in range(1, 8)
    ] + [SimpleNamespace(id=8, knowledge_entry_id=200)]

    assert diversify_ranked_chunks(chunks, max_per_source=1) == [(1, 1), (2, 8)]


def test_full_text_candidate_statement_builds_one_query_and_bounded_coarse_limit() -> None:
    async def _statement():
        async with SessionLocal() as db:
            candidates = PlatformPgVectorCandidateRetriever(db, embedding_client=None)
            return candidates._full_text_statement(
                query="annual leave",
                organization_id=7,
                user_id=11,
                allowed_ids=[13],
                allowed_revisions=[(13, "a" * 64)],
                coarse_limit=500,
            )

    import asyncio

    statement = asyncio.run(_statement())
    sql = str(statement.compile(dialect=postgresql.dialect())).lower()
    assert sql.count("plainto_tsquery(") == 1
    assert "limit" in sql
    compiled = statement.compile(dialect=postgresql.dialect())
    assert 500 in compiled.params.values()


@pytest.mark.asyncio
async def test_postgres_full_text_candidates_disable_seqscan_for_the_request_query() -> None:
    class RecordingDb:
        statements: list[str] = []

        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        async def execute(self, statement):
            self.statements.append(str(statement).lower())

        async def scalars(self, statement):
            self.statements.append(str(statement).lower())
            return SimpleNamespace(all=lambda: [])

    db = RecordingDb()
    candidates = PlatformPgVectorCandidateRetriever(db, embedding_client=None)

    result = await candidates._full_text_candidates(
        query="common policy term",
        organization_id=7,
        user_id=11,
        allowed_ids=[13],
        allowed_revisions=[(13, 99, "a" * 64)],
    )

    assert result == []
    assert db.statements[0] == "set local enable_seqscan = off"
    assert "to_tsvector" in db.statements[1]
    assert db.statements[2] == "set local enable_seqscan = on"


@pytest.mark.asyncio
async def test_candidate_statement_uses_authorized_owner_revision_tuple() -> None:
    async with SessionLocal() as db:
        candidates = PlatformPgVectorCandidateRetriever(db, embedding_client=None)
        statement = candidates._scoped_chunks_statement(
            organization_id=7,
            user_id=11,
            allowed_ids=[13],
            allowed_revisions=[(13, 99, "a" * 64)],
        )

    sql = str(statement.compile(dialect=postgresql.dialect())).lower()
    assert "knowledge_chunks.organization_id" in sql
    assert "knowledge_chunks.knowledge_entry_id in" in sql
    assert (
        "(knowledge_chunks.knowledge_entry_id, knowledge_chunks.user_id, "
        "knowledge_chunks.content_sha256)"
    ) in sql
    assert "knowledge_chunks.user_id =" not in sql


async def add_indexed_revision(
    entry_id: int,
    *,
    status: str,
    revision: str,
    texts: list[str],
) -> None:
    async with SessionLocal() as db:
        entry = await db.get(KnowledgeEntry, entry_id)
        assert entry is not None
        db.add(
            KnowledgeIngestionJob(
                organization_id=entry.organization_id,
                user_id=entry.user_id,
                knowledge_entry_id=entry.id,
                content_sha256=revision,
                status=status,
                attempts=1,
                parser_version="test-v1",
                embedding_model="text-embedding-v4",
                embedding_dimension=1024,
            )
        )
        db.add_all(
            [
                KnowledgeChunk(
                    organization_id=entry.organization_id,
                    user_id=entry.user_id,
                    knowledge_entry_id=entry.id,
                    content_sha256=revision,
                    ordinal=ordinal,
                    text=text,
                    text_sha256=sha256(text.encode()).hexdigest(),
                    source_locator=f"chunk:{ordinal}",
                    embedding=[0.1] * 1024,
                )
                for ordinal, text in enumerate(texts)
            ]
        )
        await db.commit()


@pytest.mark.asyncio
async def test_retrieve_enforces_ready_scope_budgets_and_full_text_fallback(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    ready = await client.post(
        "/api/knowledge",
        headers=admin_headers,
        json={"type": "workflow_result", "title": "Ready source", "content": "indexed"},
    )
    revoked = await client.post(
        "/api/knowledge",
        headers=admin_headers,
        json={"type": "workflow_result", "title": "Revoked source", "content": "revoked"},
    )
    assert ready.status_code == 201
    assert revoked.status_code == 201
    ready_id = ready.json()["id"]
    revoked_id = revoked.json()["id"]
    await add_indexed_revision(
        ready_id,
        status="ready",
        revision="a" * 64,
        texts=[f"needle {letter * 5_000}" for letter in ("a", "b", "c")],
    )
    await add_indexed_revision(
        revoked_id,
        status="cancelled",
        revision="b" * 64,
        texts=["needle revoked confidential text"],
    )

    retrieved = await client.post(
        "/api/knowledge/retrieve",
        headers=admin_headers,
        json={"query": "needle", "source_ids": [], "limit": 8},
    )

    assert retrieved.status_code == 200, retrieved.text
    body = retrieved.json()
    assert body["mode"] in {"hybrid", "degraded_full_text"}
    assert [citation["entry_id"] for citation in body["citations"]] == [ready_id]
    assert sum(len(citation["text"]) for citation in body["citations"]) <= 12_000
    assert "revoked confidential text" not in retrieved.text

    revoked_only = await client.post(
        "/api/knowledge/retrieve",
        headers=admin_headers,
        json={"query": "needle", "source_ids": [revoked_id]},
    )
    assert revoked_only.status_code == 200
    assert revoked_only.json() == {"citations": [], "mode": "empty"}

    legacy = await client.post(
        "/api/knowledge/search",
        headers=admin_headers,
        json={"query": "needle"},
    )
    assert legacy.status_code == 200
    assert legacy.json()["provider"] == "platform-pgvector"
    assert [item["id"] for item in legacy.json()["items"]] == [ready_id]


@pytest.mark.asyncio
async def test_successful_query_embedding_enters_authorized_hybrid_retrieval(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    created = await client.post(
        "/api/knowledge",
        headers=admin_headers,
        json={"type": "workflow_result", "title": "Hybrid", "content": "indexed"},
    )
    assert created.status_code == 201
    entry_id = created.json()["id"]
    await add_indexed_revision(
        entry_id,
        status="ready",
        revision="9" * 64,
        texts=["hybrid needle policy"],
    )

    class SuccessfulQueryEmbeddings:
        calls: list[list[str]] = []

        async def embed(self, texts):
            self.calls.append(list(texts))
            return [[0.1] * 1024 for _text in texts]

    embeddings = SuccessfulQueryEmbeddings()
    async with SessionLocal() as db:
        candidates = PlatformPgVectorCandidateRetriever(db, embedding_client=embeddings)
        result = await candidates.retrieve(
            "hybrid needle",
            [
                AuthorizedKnowledgeSource(
                    entry_id=entry_id,
                    title="Hybrid",
                    content_sha256="9" * 64,
                    organization_id=1,
                    user_id=1,
                )
            ],
            8,
        )

    assert embeddings.calls == [["hybrid needle"]]
    assert result.mode == "hybrid"
    assert [citation.entry_id for citation in result.citations] == [entry_id]
