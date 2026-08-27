from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.database import SessionLocal
from app.services import memory_retrieval
from app.models import MemoryRecord
from app.services.embedding_client import EmbeddingUnavailable
from app.services.memory_retrieval import (
    MemoryRetrievalScope,
    build_memory_fts_statement,
    build_memory_vector_statement,
    retrieve_authorized_memories,
)


async def seed_memories() -> None:
    async with SessionLocal() as db:
        for memory_id, user_id, organization_id, status, content in [
            ("authorized-memory-1", 1, 1, "active", "Friday planning deadline"),
            ("other-user-memory", 2, 1, "active", "Friday planning deadline"),
            ("other-org-memory", 1, 2, "active", "Friday planning deadline"),
            ("candidate-memory", 1, 1, "candidate", "Friday planning deadline"),
            ("superseded-memory", 1, 1, "superseded", "Friday planning deadline"),
        ]:
            db.add(
                MemoryRecord(
                    memory_id=memory_id,
                    organization_id=organization_id,
                    user_id=user_id,
                    content=content,
                    type="fact",
                    layer="L1",
                    status=status,
                    origin="manual",
                    revision=1,
                    metadata_={},
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )
        await db.commit()


@pytest.mark.asyncio
async def test_retrieval_applies_owner_and_active_scope_before_text_match() -> None:
    await seed_memories()
    async with SessionLocal() as db:
        items = await retrieve_authorized_memories(
            db,
            scope=MemoryRetrievalScope(organization_id=1, user_id=1),
            query="Friday planning",
            limit=10,
        )
    assert [item.memory_id for item in items] == ["authorized-memory-1"]


def test_postgres_retrieval_statements_scope_before_fts_and_vector_ranking() -> None:
    scope = MemoryRetrievalScope(organization_id=7, user_id=11)
    fts = str(
        build_memory_fts_statement(scope=scope, query="planning", limit=10).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    ).lower()
    vector = str(
        build_memory_vector_statement(
            scope=scope,
            vector=[0.0] * 1024,
            limit=10,
        ).compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    ).lower()
    for sql in (fts, vector):
        assert "organization_id = 7" in sql
        assert "user_id = 11" in sql
        assert "status = 'active'" in sql
    assert "to_tsvector" in fts and "websearch_to_tsquery" in fts
    assert "<=>" in vector


@pytest.mark.asyncio
async def test_deterministic_vector_rrf_is_scoped_and_filtered() -> None:
    basis = [0.0] * 1024
    basis[0] = 1.0
    async with SessionLocal() as db:
        now = datetime.now(UTC)
        db.add_all(
            [
                MemoryRecord(
                    memory_id=memory_id,
                    organization_id=organization_id,
                    user_id=user_id,
                    content=content,
                    type=memory_type,
                    layer=layer,
                    status=status,
                    origin="manual",
                    revision=1,
                    metadata_={},
                    embedding=embedding,
                    embedding_state="ready",
                    created_at=now,
                    updated_at=now,
                )
                for memory_id, organization_id, user_id, content, memory_type, layer, status, embedding in [
                    ("rrf-overlap", 1, 1, "planning marker", "fact", "L1", "active", basis),
                    ("vector-only", 1, 1, "semantic deadline", "fact", "L1", "active", basis),
                    ("wrong-layer", 1, 1, "planning marker", "fact", "L2", "active", basis),
                    ("other-owner-vector", 1, 2, "planning marker", "fact", "L1", "active", basis),
                    ("other-org-vector", 2, 1, "planning marker", "fact", "L1", "active", basis),
                    ("candidate-vector", 1, 1, "planning marker", "fact", "L1", "candidate", basis),
                ]
            ]
        )
        await db.commit()

        class FakeEmbedding:
            async def embed(self, texts):
                assert texts == ["planning marker"]
                return [basis]

        items = await retrieve_authorized_memories(
            db,
            scope=MemoryRetrievalScope(organization_id=1, user_id=1),
            query="planning marker",
            limit=5,
            memory_types=("fact",),
            layers=("L1",),
            embedding_provider=FakeEmbedding(),
        )

    ids = [item.memory_id for item in items]
    assert ids[0] == "rrf-overlap"
    assert set(ids) == {"rrf-overlap", "vector-only"}


@pytest.mark.asyncio
async def test_embedding_unavailable_degrades_to_authorized_fts() -> None:
    await seed_memories()

    class UnavailableEmbedding:
        async def embed(self, texts):
            del texts
            raise EmbeddingUnavailable("embedding_unavailable")

    async with SessionLocal() as db:
        items = await retrieve_authorized_memories(
            db,
            scope=MemoryRetrievalScope(organization_id=1, user_id=1),
            query="Friday planning",
            embedding_provider=UnavailableEmbedding(),
        )
    assert [item.memory_id for item in items] == ["authorized-memory-1"]


@pytest.mark.asyncio
async def test_postgres_vector_retrieval_keeps_ann_when_exact_sample_has_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    ann_only = MemoryRecord(
        memory_id="older-ann-semantic-match",
        organization_id=1,
        user_id=1,
        content="older semantic match",
        type="fact",
        layer="L1",
        status="active",
        origin="manual",
        revision=1,
        metadata_={},
        updated_at=now,
        created_at=now,
    )
    exact_sample = MemoryRecord(
        memory_id="recent-exact-sample",
        organization_id=1,
        user_id=1,
        content="recent exact sample",
        type="fact",
        layer="L1",
        status="active",
        origin="manual",
        revision=1,
        metadata_={},
        updated_at=now,
        created_at=now,
    )

    class FakeScalarResult:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class FakePostgresDb:
        def __init__(self):
            self._calls = 0

        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        async def scalars(self, _statement):
            self._calls += 1
            if self._calls == 1:
                return FakeScalarResult([])
            if self._calls == 2:
                return FakeScalarResult([ann_only])
            raise AssertionError("unexpected scalar query")

    class FakeEmbedding:
        async def embed(self, texts):
            assert texts == ["semantic query"]
            return [[1.0] + [0.0] * 1023]

    async def exact_candidates(*_args, **_kwargs):
        return [exact_sample]

    monkeypatch.setattr(
        memory_retrieval,
        "_bounded_exact_vector_candidates",
        exact_candidates,
    )

    items = await retrieve_authorized_memories(
        FakePostgresDb(),
        scope=MemoryRetrievalScope(organization_id=1, user_id=1),
        query="semantic query",
        limit=10,
        embedding_provider=FakeEmbedding(),
    )

    assert {item.memory_id for item in items} == {
        "older-ann-semantic-match",
        "recent-exact-sample",
    }
