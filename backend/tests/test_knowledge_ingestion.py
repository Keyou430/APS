from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, update
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.dml import Delete

from app.auth.security import hash_password
from app.config import Settings, get_settings
from app.database import SessionLocal
from app.models import (
    KnowledgeChunk,
    KnowledgeEntry,
    KnowledgeIngestionJob,
    Organization,
    OrganizationMembership,
    Role,
    User,
)
from app.routers import knowledge as knowledge_router
from app.services import knowledge_ingestion
from app.services.document_parser import DoclingDocumentParser
from app.services.embedding_client import EmbeddingClient, EmbeddingUnavailable
from app.services.object_storage import LocalPrivateObjectStorage
from app.workers import rag_ingestion


@pytest.mark.asyncio
async def test_ingestion_enqueue_and_status_redact_knowledge_content(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    secret_content = "confidential ingestion source"
    created = await client.post(
        "/api/knowledge",
        headers=admin_headers,
        json={
            "type": "workflow_result",
            "title": "Ingestion source",
            "content": secret_content,
        },
    )
    assert created.status_code == 201, created.text

    queued = await client.post(
        f"/api/knowledge/{created.json()['id']}/ingest",
        headers=admin_headers,
    )

    assert queued.status_code == 202, queued.text
    assert set(queued.json()) == {
        "id",
        "status",
        "attempts",
        "embedding_model",
        "embedding_dimension",
        "error_code",
        "created_at",
    }
    assert queued.json()["status"] == "queued"
    assert secret_content not in queued.text

    status = await client.get(
        f"/api/knowledge/{created.json()['id']}/ingestion",
        headers=admin_headers,
    )

    assert status.status_code == 200, status.text
    assert status.json()["id"] == queued.json()["id"]
    assert secret_content not in status.text


@pytest.mark.asyncio
async def test_enqueue_is_idempotent_for_same_entry_content(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    created = await client.post(
        "/api/knowledge",
        headers=admin_headers,
        json={"type": "workflow_result", "title": "Stable", "content": "same content"},
    )
    path = f"/api/knowledge/{created.json()['id']}/ingest"

    first = await client.post(path, headers=admin_headers)
    second = await client.post(path, headers=admin_headers)

    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text
    assert second.json()["id"] == first.json()["id"]


def test_claim_statement_uses_skip_locked_only_for_postgresql() -> None:
    postgresql_statement = knowledge_ingestion.queued_job_claim_statement("postgresql")
    sqlite_statement = knowledge_ingestion.queued_job_claim_statement("sqlite")

    compiled_postgresql = str(
        postgresql_statement.compile(dialect=postgresql.dialect())
    ).upper()
    compiled_sqlite = str(sqlite_statement.compile(dialect=sqlite.dialect())).upper()

    assert "FOR UPDATE SKIP LOCKED" in compiled_postgresql
    assert "FOR UPDATE" not in compiled_sqlite


def test_cancel_statement_locks_jobs_only_for_postgresql() -> None:
    postgresql_statement = knowledge_ingestion.active_ingestion_cancel_statement(
        "postgresql", 42
    )
    sqlite_statement = knowledge_ingestion.active_ingestion_cancel_statement("sqlite", 42)

    compiled_postgresql = str(
        postgresql_statement.compile(dialect=postgresql.dialect())
    ).upper()
    compiled_sqlite = str(sqlite_statement.compile(dialect=sqlite.dialect())).upper()

    assert "FOR UPDATE" in compiled_postgresql
    assert "FOR UPDATE" not in compiled_sqlite


@pytest.mark.asyncio
async def test_sqlite_concurrent_claim_is_single_winner_and_increments_attempts(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    async with SessionLocal() as db:
        await db.execute(
            update(KnowledgeIngestionJob)
            .where(KnowledgeIngestionJob.status.in_(("queued", "processing")))
            .values(status="cancelled")
        )
        await db.commit()
    created = await client.post(
        "/api/knowledge",
        headers=admin_headers,
        json={"type": "workflow_result", "title": "Claim", "content": "claim once"},
    )
    queued = await client.post(
        f"/api/knowledge/{created.json()['id']}/ingest",
        headers=admin_headers,
    )
    job_id = queued.json()["id"]

    async def claim() -> int | None:
        async with SessionLocal() as db:
            job = await knowledge_ingestion.claim_next_job(db)
            return job.id if job is not None else None

    claimed = await asyncio.gather(claim(), claim())

    assert sorted(value for value in claimed if value is not None) == [job_id]
    async with SessionLocal() as db:
        persisted = await db.get(KnowledgeIngestionJob, job_id)
        assert persisted is not None
        assert persisted.status == "processing"
        assert persisted.attempts == 1


@pytest.mark.asyncio
async def test_processor_atomically_replaces_old_chunks_and_marks_job_ready(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    async with SessionLocal() as db:
        await db.execute(delete(KnowledgeChunk))
        await db.execute(
            update(KnowledgeIngestionJob)
            .where(KnowledgeIngestionJob.status.in_(("queued", "processing")))
            .values(status="cancelled")
        )
        await db.commit()
    created = await client.post(
        "/api/knowledge",
        headers=admin_headers,
        json={
            "type": "workflow_result",
            "title": "Versioned source",
            "content": "current deterministic content",
        },
    )
    entry_id = created.json()["id"]
    queued = await client.post(f"/api/knowledge/{entry_id}/ingest", headers=admin_headers)
    job_id = queued.json()["id"]
    async with SessionLocal() as db:
        db.add(
            KnowledgeChunk(
                organization_id=1,
                user_id=1,
                knowledge_entry_id=entry_id,
                content_sha256="b" * 64,
                ordinal=0,
                text="previous version",
                text_sha256="c" * 64,
                source_locator="chunk:0",
                embedding=[0.0] * 1024,
            )
        )
        await db.commit()

    class UnusedStorage:
        async def open_read(self, _object_key: str) -> bytes:
            raise AssertionError("workflow content must come from platform persistence")

    class UnusedParser:
        def parse(self, _path):
            raise AssertionError("workflow content must not use Docling")

    class RecordingEmbeddings:
        calls: list[list[str]] = []

        async def embed(self, texts):
            self.calls.append(list(texts))
            return [[0.25] * 1024 for _text in texts]

    embeddings = RecordingEmbeddings()
    processor = knowledge_ingestion.KnowledgeIngestionProcessor(
        SessionLocal,
        storage=UnusedStorage(),
        parser=UnusedParser(),
        embedding_client=embeddings,
    )

    assert await processor.process_next() is True

    async with SessionLocal() as db:
        job = await db.get(KnowledgeIngestionJob, job_id)
        chunks = list(
            (
                await db.scalars(
                    select(KnowledgeChunk)
                    .where(KnowledgeChunk.knowledge_entry_id == entry_id)
                    .order_by(KnowledgeChunk.ordinal)
                )
            ).all()
        )
    assert job is not None
    assert job.status == "ready"
    assert job.attempts == 1
    assert len(chunks) == len(embeddings.calls[0])
    assert {chunk.content_sha256 for chunk in chunks} == {job.content_sha256}
    assert [chunk.ordinal for chunk in chunks] == list(range(len(chunks)))


@pytest.mark.asyncio
async def test_processor_retries_failures_three_times_without_replacing_old_chunks(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    async with SessionLocal() as db:
        await db.execute(delete(KnowledgeChunk))
        await db.execute(
            update(KnowledgeIngestionJob)
            .where(KnowledgeIngestionJob.status.in_(("queued", "processing")))
            .values(status="cancelled")
        )
        await db.commit()
    created = await client.post(
        "/api/knowledge",
        headers=admin_headers,
        json={"type": "workflow_result", "title": "Retry", "content": "new source"},
    )
    entry_id = created.json()["id"]
    queued = await client.post(f"/api/knowledge/{entry_id}/ingest", headers=admin_headers)
    job_id = queued.json()["id"]
    async with SessionLocal() as db:
        db.add(
            KnowledgeChunk(
                organization_id=1,
                user_id=1,
                knowledge_entry_id=entry_id,
                content_sha256="d" * 64,
                ordinal=0,
                text="still available",
                text_sha256="e" * 64,
                source_locator="chunk:0",
                embedding=[0.0] * 1024,
            )
        )
        await db.commit()

    class FailingEmbeddings:
        async def embed(self, _texts):
            raise EmbeddingUnavailable("embedding_unavailable")

    processor = knowledge_ingestion.KnowledgeIngestionProcessor(
        SessionLocal,
        storage=object(),
        parser=object(),
        embedding_client=FailingEmbeddings(),
    )

    assert await processor.process_next() is True
    async with SessionLocal() as db:
        first = await db.get(KnowledgeIngestionJob, job_id)
        old_chunks = list(
            (
                await db.scalars(
                    select(KnowledgeChunk).where(KnowledgeChunk.knowledge_entry_id == entry_id)
                )
            ).all()
        )
        assert first is not None
        assert (first.status, first.attempts, first.last_error_code) == (
            "queued",
            1,
            "embedding_unavailable",
        )
        assert [chunk.text for chunk in old_chunks] == ["still available"]

    assert await processor.process_next() is True
    assert await processor.process_next() is True
    async with SessionLocal() as db:
        final = await db.get(KnowledgeIngestionJob, job_id)
        assert final is not None
        assert (final.status, final.attempts, final.last_error_code) == (
            "failed",
            3,
            "embedding_unavailable",
        )


@pytest.mark.asyncio
async def test_post_flush_failure_rolls_back_new_chunks_and_preserves_old_version(
    client: AsyncClient,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with SessionLocal() as db:
        await db.execute(delete(KnowledgeChunk))
        await db.execute(
            update(KnowledgeIngestionJob)
            .where(KnowledgeIngestionJob.status.in_(("queued", "processing")))
            .values(status="cancelled")
        )
        await db.commit()
    created = await client.post(
        "/api/knowledge",
        headers=admin_headers,
        json={"type": "workflow_result", "title": "Rollback", "content": "new version"},
    )
    entry_id = created.json()["id"]
    queued = await client.post(f"/api/knowledge/{entry_id}/ingest", headers=admin_headers)
    job_id = queued.json()["id"]
    async with SessionLocal() as db:
        db.add(
            KnowledgeChunk(
                organization_id=1,
                user_id=1,
                knowledge_entry_id=entry_id,
                content_sha256="f" * 64,
                ordinal=0,
                text="old committed version",
                text_sha256="1" * 64,
                source_locator="chunk:0",
                embedding=[0.0] * 1024,
            )
        )
        await db.commit()

    class SuccessfulEmbeddings:
        async def embed(self, texts):
            return [[0.75] * 1024 for _text in texts]

    original_execute = AsyncSession.execute

    async def fail_obsolete_chunk_delete(self, statement, *args, **kwargs):
        if isinstance(statement, Delete) and statement.table.name == "knowledge_chunks":
            raise RuntimeError("post_flush_failure")
        return await original_execute(self, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", fail_obsolete_chunk_delete)
    processor = knowledge_ingestion.KnowledgeIngestionProcessor(
        SessionLocal,
        storage=object(),
        parser=object(),
        embedding_client=SuccessfulEmbeddings(),
    )

    assert await processor.process_next() is True

    async with SessionLocal() as db:
        job = await db.get(KnowledgeIngestionJob, job_id)
        chunks = list(
            (
                await db.scalars(
                    select(KnowledgeChunk).where(KnowledgeChunk.knowledge_entry_id == entry_id)
                )
            ).all()
        )
    assert job is not None
    assert (job.status, job.attempts, job.last_error_code) == (
        "queued",
        1,
        "ingestion_failed",
    )
    assert [(chunk.content_sha256, chunk.text) for chunk in chunks] == [
        ("f" * 64, "old committed version")
    ]


@pytest.mark.asyncio
async def test_file_ingestion_reads_private_storage_through_temporary_docling_file(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    collection = await client.post(
        "/api/knowledge/collections", headers=admin_headers, json={"name": "摄入测试"}
    )
    assert collection.status_code == 201, collection.text
    async with SessionLocal() as db:
        await db.execute(
            update(KnowledgeIngestionJob)
            .where(KnowledgeIngestionJob.status.in_(("queued", "processing")))
            .values(status="cancelled")
        )
        await db.commit()
    private_bytes = b"private file bytes"
    uploaded = await client.post(
        "/api/knowledge/upload",
        headers=admin_headers,
        data={"title": "Private file", "collection_id": str(collection.json()["id"])},
        files={"file": ("notes.txt", private_bytes, "text/plain")},
    )
    entry_id = uploaded.json()["id"]
    queued = await client.post(f"/api/knowledge/{entry_id}/ingest", headers=admin_headers)
    job_id = queued.json()["id"]

    class RecordingParser:
        seen_path: Path | None = None
        thread_id: int | None = None

        def parse(self, path: Path):
            self.seen_path = path
            self.thread_id = threading.get_ident()
            assert path.is_file()
            assert path.suffix == ".txt"
            assert path.read_bytes() == private_bytes
            return SimpleNamespace(markdown="parsed private document")

    class SuccessfulEmbeddings:
        async def embed(self, texts):
            return [[0.5] * 1024 for _text in texts]

    parser = RecordingParser()
    event_loop_thread_id = threading.get_ident()
    processor = knowledge_ingestion.KnowledgeIngestionProcessor(
        SessionLocal,
        storage=LocalPrivateObjectStorage(get_settings().upload_dir),
        parser=parser,
        embedding_client=SuccessfulEmbeddings(),
    )

    assert await processor.process_next() is True

    assert parser.seen_path is not None
    assert parser.thread_id != event_loop_thread_id
    assert not parser.seen_path.exists()
    async with SessionLocal() as db:
        job = await db.get(KnowledgeIngestionJob, job_id)
        assert job is not None
        assert job.status == "ready"


@pytest.mark.asyncio
async def test_purge_preserves_archived_entry_when_private_object_delete_fails(
    client: AsyncClient,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = await client.post(
        "/api/knowledge/collections", headers=admin_headers, json={"name": "删除测试"}
    )
    assert collection.status_code == 201, collection.text
    uploaded = await client.post(
        "/api/knowledge/upload",
        headers=admin_headers,
        data={"title": "Cannot delete object", "collection_id": str(collection.json()["id"])},
        files={"file": ("cannot-delete.txt", b"private", "text/plain")},
    )
    entry_id = uploaded.json()["id"]
    queued = await client.post(f"/api/knowledge/{entry_id}/ingest", headers=admin_headers)
    job_id = queued.json()["id"]
    cancellation_observed: list[str] = []
    real_cancel = knowledge_router.cancel_active_ingestions

    async def record_cancel(db, cancelled_entry_id: int) -> None:
        await real_cancel(db, cancelled_entry_id)
        job = await db.get(KnowledgeIngestionJob, job_id)
        assert job is not None
        cancellation_observed.append(job.status)

    async def object_delete_fails(_file_reference: str) -> None:
        raise OSError("object delete failed")

    monkeypatch.setattr(knowledge_router, "cancel_active_ingestions", record_cancel)
    monkeypatch.setattr(knowledge_router, "delete_stored_file", object_delete_fails)

    archived = await client.delete(f"/api/knowledge/{entry_id}", headers=admin_headers)
    assert archived.status_code == 204
    with pytest.raises(OSError, match="object delete failed"):
        await client.delete(f"/api/knowledge/{entry_id}/purge", headers=admin_headers)

    async with SessionLocal() as db:
        entry = await db.get(KnowledgeEntry, entry_id)
        job = await db.get(KnowledgeIngestionJob, job_id)
    assert entry is not None
    assert entry.archived_at is not None
    assert job is not None
    assert cancellation_observed == ["cancelled"]
    assert job.status == "cancelled"


@pytest.mark.asyncio
async def test_ingestion_endpoints_return_404_for_another_user(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    secret_content = "owner-only ingestion content"
    created = await client.post(
        "/api/knowledge",
        headers=admin_headers,
        json={"type": "workflow_result", "title": "Owner", "content": secret_content},
    )
    entry_id = created.json()["id"]
    await client.post(f"/api/knowledge/{entry_id}/ingest", headers=admin_headers)
    created_user = await client.post(
        "/api/users",
        headers=admin_headers,
        json={
            "username": "ingestion-other-user",
            "password": "tenant-password",
            "email": "ingestion-other-user@example.com",
            "role": "user",
        },
    )
    assert created_user.status_code == 201, created_user.text
    login = await client.post(
        "/api/auth/login",
        json={"username": "ingestion-other-user", "password": "tenant-password"},
    )
    other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    enqueue = await client.post(f"/api/knowledge/{entry_id}/ingest", headers=other_headers)
    status = await client.get(f"/api/knowledge/{entry_id}/ingestion", headers=other_headers)

    assert enqueue.status_code == 404
    assert status.status_code == 404
    assert secret_content not in enqueue.text
    assert secret_content not in status.text


@pytest.mark.asyncio
async def test_ingestion_endpoints_return_404_for_another_organization(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    secret_content = "organization-only ingestion content"
    created = await client.post(
        "/api/knowledge",
        headers=admin_headers,
        json={"type": "workflow_result", "title": "Organization", "content": secret_content},
    )
    entry_id = created.json()["id"]
    await client.post(f"/api/knowledge/{entry_id}/ingest", headers=admin_headers)
    async with SessionLocal() as db:
        role = await db.scalar(select(Role).where(Role.name == "user"))
        assert role is not None
        organization = Organization(name="Other Organization", slug="other-ingestion-org")
        db.add(organization)
        await db.flush()
        user = User(
            username="ingestion-other-org-user",
            email="ingestion-other-org-user@example.com",
            password_hash=hash_password("tenant-password"),
            role_id=role.id,
            default_organization_id=organization.id,
        )
        db.add(user)
        await db.flush()
        db.add(
            OrganizationMembership(
                organization_id=organization.id,
                user_id=user.id,
                role_id=role.id,
            )
        )
        await db.commit()

    login = await client.post(
        "/api/auth/login",
        json={"username": "ingestion-other-org-user", "password": "tenant-password"},
    )
    other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    enqueue = await client.post(f"/api/knowledge/{entry_id}/ingest", headers=other_headers)
    status = await client.get(f"/api/knowledge/{entry_id}/ingestion", headers=other_headers)

    assert enqueue.status_code == 404
    assert status.status_code == 404
    assert secret_content not in enqueue.text
    assert secret_content not in status.text
    async with SessionLocal() as db:
        other_user = await db.scalar(
            select(User).where(User.username == "ingestion-other-org-user")
        )
        assert other_user is not None
        await db.execute(
            delete(OrganizationMembership).where(
                OrganizationMembership.user_id == other_user.id
            )
        )
        await db.delete(other_user)
        other_organization = await db.scalar(
            select(Organization).where(Organization.slug == "other-ingestion-org")
        )
        assert other_organization is not None
        await db.delete(other_organization)
        await db.commit()


@pytest.mark.asyncio
async def test_worker_builds_processor_and_main_only_runs_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert hasattr(rag_ingestion, "build_processor")
    assert hasattr(rag_ingestion, "main")

    class SentinelSessionFactory:
        pass

    settings = get_settings().model_copy(
        update={
            "rag_embedding_enabled": True,
            "rag_embedding_api_url": "https://embedding.invalid/v1",
            "rag_embedding_api_key": "unit-test-credential",
        }
    )
    processor = rag_ingestion.build_processor(settings, session_factory=SentinelSessionFactory)
    assert processor._session_factory is SentinelSessionFactory
    assert isinstance(processor._storage, LocalPrivateObjectStorage)
    assert isinstance(processor._parser, DoclingDocumentParser)
    assert isinstance(processor._embedding_client, EmbeddingClient)

    observed: dict[str, object] = {}

    def build_recording_processor(*_args, **_kwargs):
        return processor

    async def run_recording_worker(received, *, stop_event, poll_seconds):
        observed.update(processor=received, stop_event=stop_event, poll_seconds=poll_seconds)

    stop_event = asyncio.Event()
    monkeypatch.setattr(rag_ingestion, "get_settings", lambda: settings)
    monkeypatch.setattr(rag_ingestion, "build_processor", build_recording_processor)
    monkeypatch.setattr(rag_ingestion, "run_worker", run_recording_worker)

    await rag_ingestion.main(stop_event=stop_event)

    assert observed["processor"] is processor
    assert observed["stop_event"] is stop_event


@pytest.mark.parametrize(
    ("api_url", "api_key"),
    [
        (None, None),
        ("https://embedding.invalid/v1", None),
        (None, "unit-test-credential"),
    ],
)
def test_worker_build_processor_fails_closed_without_complete_embedding_configuration(
    api_url: str | None,
    api_key: str | None,
) -> None:
    settings = Settings(
        database_url="sqlite+aiosqlite:///./worker-build-test.db",
        jwt_secret_key="worker-build-test-secret",
        rag_embedding_api_url=api_url,
        rag_embedding_api_key=api_key,
    )

    with pytest.raises(RuntimeError, match="RAG embedding configuration is incomplete"):
        rag_ingestion.build_processor(settings)


@pytest.mark.asyncio
async def test_empty_source_is_failed_without_marking_job_ready(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    async with SessionLocal() as db:
        await db.execute(
            update(KnowledgeIngestionJob)
            .where(KnowledgeIngestionJob.status.in_(("queued", "processing")))
            .values(status="cancelled")
        )
        await db.commit()
    created = await client.post(
        "/api/knowledge",
        headers=admin_headers,
        json={"type": "workflow_result", "title": "Empty", "content": "   \n\t"},
    )
    queued = await client.post(
        f"/api/knowledge/{created.json()['id']}/ingest",
        headers=admin_headers,
    )

    class EmptySafeEmbeddings:
        async def embed(self, _texts):
            return []

    processor = knowledge_ingestion.KnowledgeIngestionProcessor(
        SessionLocal,
        storage=object(),
        parser=object(),
        embedding_client=EmptySafeEmbeddings(),
    )

    assert await processor.process_next() is True
    async with SessionLocal() as db:
        job = await db.get(KnowledgeIngestionJob, queued.json()["id"])
    assert job is not None
    assert (job.status, job.attempts, job.last_error_code) == ("queued", 1, "empty_document")
