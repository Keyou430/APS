from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql, sqlite
from types import SimpleNamespace

from app import models
from app.database import Base


MIGRATION_PATH = (
    Path(__file__).parents[1] / "migrations" / "versions" / "20260729_0005_platform_rag.py"
)


class RecordingOperations:
    def __init__(self, dialect_name: str = "postgresql") -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self._bind = SimpleNamespace(dialect=SimpleNamespace(name=dialect_name))

    def get_bind(self) -> Any:
        return self._bind

    def batch_alter_table(self, *args: Any, **kwargs: Any) -> "RecordingOperations":
        self.calls.append(("batch_alter_table", args, kwargs))
        return self

    def __enter__(self) -> "RecordingOperations":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def __getattr__(self, name: str) -> Any:
        def record(*args: Any, **kwargs: Any) -> None:
            self.calls.append((name, args, kwargs))

        return record


def load_migration() -> ModuleType:
    assert MIGRATION_PATH.is_file(), "platform RAG migration is missing"
    spec = importlib.util.spec_from_file_location("platform_rag_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def calls_named(
    operations: RecordingOperations, name: str
) -> list[tuple[tuple[Any, ...], dict[str, Any]]]:
    return [(args, kwargs) for call_name, args, kwargs in operations.calls if call_name == name]


def test_rag_models_preserve_scope_and_sqlite_create_all() -> None:
    expected_models = (
        "KnowledgeIngestionJob",
        "KnowledgeChunk",
        "KnowledgeRetrievalEvent",
    )
    assert all(hasattr(models, name) for name in expected_models), "RAG models are missing"

    expected_columns = {
        "knowledge_ingestion_jobs": {
            "id",
            "organization_id",
            "user_id",
            "knowledge_entry_id",
            "content_sha256",
            "status",
            "attempts",
            "parser_version",
            "embedding_model",
            "embedding_dimension",
            "last_error_code",
            "created_at",
        },
        "knowledge_chunks": {
            "id",
            "organization_id",
            "user_id",
            "knowledge_entry_id",
            "content_sha256",
            "ordinal",
            "text",
            "text_sha256",
            "source_locator",
            "embedding",
            "created_at",
        },
        "knowledge_retrieval_events": {
            "id",
            "organization_id",
            "user_id",
            "chat_session_id",
                "query_sha256",
                "query_hmac",
                "query_hmac_version",
                "request_kind",
                "retrieval_mode",
            "result_count",
            "latency_ms",
            "outcome",
            "created_at",
        },
    }
    expected_foreign_keys = {
        "knowledge_ingestion_jobs": {
            ("knowledge_entry_id", "knowledge_entries.id", "CASCADE")
        },
        "knowledge_chunks": {
            ("knowledge_entry_id", "knowledge_entries.id", "CASCADE")
        },
            "knowledge_retrieval_events": {
                ("chat_session_id", "chat_sessions.id", "SET NULL")
            },
    }
    for table_name, columns in expected_columns.items():
        table = Base.metadata.tables[table_name]
        assert set(table.columns.keys()) == columns
        assert table.c.created_at.nullable is False
        actual_foreign_keys = {
            (foreign_key.parent.name, foreign_key.target_fullname, foreign_key.ondelete)
            for foreign_key in table.foreign_keys
        }
        assert actual_foreign_keys == expected_foreign_keys[table_name]

    chunks = Base.metadata.tables["knowledge_chunks"]
    assert chunks.c.embedding.type.compile(dialect=postgresql.dialect()) == "VECTOR(1024)"
    assert chunks.c.embedding.type.compile(dialect=sqlite.dialect()) == "JSON"

    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sqlite_chunk_indexes = {
        index["name"] for index in sa.inspect(engine).get_indexes("knowledge_chunks")
    }
    assert sqlite_chunk_indexes == {"ix_knowledge_chunks_scope"}
    engine.dispose()


def test_rag_model_metadata_declares_postgresql_retrieval_indexes() -> None:
    expected_scope_indexes = {
        "knowledge_ingestion_jobs": "ix_knowledge_ingestion_jobs_scope",
        "knowledge_chunks": "ix_knowledge_chunks_scope",
        "knowledge_retrieval_events": "ix_knowledge_retrieval_events_scope",
    }
    for table_name, index_name in expected_scope_indexes.items():
        indexes = {index.name: index for index in Base.metadata.tables[table_name].indexes}
        scope = indexes[index_name]
        assert scope.dialect_options["postgresql"]["using"] in (False, None, "btree")

    chunks = Base.metadata.tables["knowledge_chunks"]
    indexes = {index.name: index for index in chunks.indexes}
    full_text = indexes["ix_knowledge_chunks_text_fts"]
    assert full_text.dialect_options["postgresql"]["using"] == "gin"
    assert "to_tsvector('simple', text)" in str(full_text.expressions[0])

    vector = indexes["ix_knowledge_chunks_embedding_hnsw"]
    assert vector.dialect_options["postgresql"]["using"] == "hnsw"
    assert vector.dialect_options["postgresql"]["ops"] == {
        "embedding": "vector_cosine_ops"
    }


def test_rag_model_uniqueness_and_new_chat_backend_default() -> None:
    jobs = Base.metadata.tables["knowledge_ingestion_jobs"]
    chunks = Base.metadata.tables["knowledge_chunks"]
    job_unique_columns = {
        tuple(constraint.columns.keys())
        for constraint in jobs.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    }
    chunk_unique_columns = {
        tuple(constraint.columns.keys())
        for constraint in chunks.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    }

    assert ("knowledge_entry_id", "content_sha256") in job_unique_columns
    assert ("knowledge_entry_id", "content_sha256", "ordinal") in chunk_unique_columns
    assert jobs.c.status.default is not None
    assert jobs.c.status.default.arg == "queued"

    backend = Base.metadata.tables["chat_sessions"].c.hermes_backend
    assert backend.nullable is False
    assert backend.type.length == 20
    assert backend.default is not None and backend.default.arg == "knowledge"


def test_upgrade_creates_pgvector_tables_indexes_and_backfills_legacy_sessions() -> None:
    migration = load_migration()
    operations = RecordingOperations()
    migration.op = operations

    migration.upgrade()

    assert migration.revision == "20260729_0005"
    assert migration.down_revision == "20260727_0004"
    executed = [str(args[0]) for args, _ in calls_named(operations, "execute")]
    assert any("CREATE EXTENSION IF NOT EXISTS vector" in statement for statement in executed)
    assert any(
        "UPDATE chat_sessions" in statement
        and "hermes_backend" in statement
        and "'agent'" in statement
        for statement in executed
    )

    created_tables = {args[0]: args[1:] for args, _ in calls_named(operations, "create_table")}
    assert set(created_tables) == {
        "knowledge_ingestion_jobs",
        "knowledge_chunks",
        "knowledge_retrieval_events",
    }
    for table_name, columns_and_constraints in created_tables.items():
        columns = {
            item.name: item
            for item in columns_and_constraints
            if isinstance(item, sa.Column)
        }
        assert columns["created_at"].nullable is False, table_name
    job_columns = {
        item.name: item
        for item in created_tables["knowledge_ingestion_jobs"]
        if isinstance(item, sa.Column)
    }
    assert job_columns["status"].server_default is not None
    assert job_columns["status"].server_default.arg == "queued"
    expected_foreign_keys = {
        "knowledge_ingestion_jobs": {
            ("knowledge_entry_id", "knowledge_entries.id", "CASCADE")
        },
        "knowledge_chunks": {
            ("knowledge_entry_id", "knowledge_entries.id", "CASCADE")
        },
        "knowledge_retrieval_events": set(),
    }
    for table_name, columns_and_constraints in created_tables.items():
        actual_foreign_keys = set()
        for item in columns_and_constraints:
            if not isinstance(item, sa.ForeignKeyConstraint):
                continue
            for local_column, element in zip(item.column_keys, item.elements, strict=True):
                actual_foreign_keys.add(
                    (local_column, element.target_fullname, item.ondelete)
                )
        assert actual_foreign_keys == expected_foreign_keys[table_name]

    chunk_columns = {
        item.name: item
        for item in created_tables["knowledge_chunks"]
        if isinstance(item, sa.Column)
    }
    assert chunk_columns["embedding"].type.compile(dialect=postgresql.dialect()) == "VECTOR(1024)"

    indexes = {args[0]: (args, kwargs) for args, kwargs in calls_named(operations, "create_index")}
    assert indexes["ix_knowledge_ingestion_jobs_scope"][0][2] == [
        "organization_id",
        "user_id",
        "knowledge_entry_id",
    ]
    assert indexes["ix_knowledge_chunks_scope"][0][2] == [
        "organization_id",
        "user_id",
        "knowledge_entry_id",
    ]
    assert indexes["ix_knowledge_chunks_scope"][1].get("postgresql_using", "btree") == "btree"
    assert (
        indexes["ix_knowledge_ingestion_jobs_scope"][1].get("postgresql_using", "btree")
        == "btree"
    )
    assert (
        indexes["ix_knowledge_retrieval_events_scope"][1].get("postgresql_using", "btree")
        == "btree"
    )
    assert indexes["ix_knowledge_chunks_text_fts"][1]["postgresql_using"] == "gin"
    assert "to_tsvector('simple', text)" in str(
        indexes["ix_knowledge_chunks_text_fts"][0][2][0]
    )
    assert indexes["ix_knowledge_chunks_embedding_hnsw"][1] == {
        "postgresql_using": "hnsw",
        "postgresql_ops": {"embedding": "vector_cosine_ops"},
    }

    added_columns = calls_named(operations, "add_column")
    backend = next(args[1] for args, _ in added_columns if args[0] == "chat_sessions")
    assert backend.name == "hermes_backend"
    assert backend.type.length == 20
    assert backend.nullable is True
    altered_columns = calls_named(operations, "alter_column")
    assert any(
        args[:2] == ("chat_sessions", "hermes_backend") and kwargs["nullable"] is False
        for args, kwargs in altered_columns
    )


def test_upgrade_skips_postgresql_extension_and_indexes_for_sqlite() -> None:
    migration = load_migration()
    operations = RecordingOperations("sqlite")
    migration.op = operations

    migration.upgrade()

    executed = [str(args[0]) for args, _ in calls_named(operations, "execute")]
    assert not any("CREATE EXTENSION" in statement for statement in executed)
    indexes = {args[0]: kwargs for args, kwargs in calls_named(operations, "create_index")}
    assert "ix_knowledge_chunks_text_fts" not in indexes
    assert "ix_knowledge_chunks_embedding_hnsw" not in indexes
    created_tables = {args[0]: args[1:] for args, _ in calls_named(operations, "create_table")}
    chunk_columns = {
        item.name: item
        for item in created_tables["knowledge_chunks"]
        if isinstance(item, sa.Column)
    }
    assert chunk_columns["embedding"].type.compile(dialect=sqlite.dialect()) == "JSON"


def test_downgrade_removes_rag_schema_without_dropping_shared_vector_extension() -> None:
    migration = load_migration()
    operations = RecordingOperations()
    migration.op = operations

    migration.downgrade()

    dropped_tables = [args[0] for args, _ in calls_named(operations, "drop_table")]
    assert dropped_tables == [
        "knowledge_retrieval_events",
        "knowledge_chunks",
        "knowledge_ingestion_jobs",
    ]
    dropped_columns = calls_named(operations, "drop_column")
    assert any(args == ("chat_sessions", "hermes_backend") for args, _ in dropped_columns)
    executed = [str(args[0]) for args, _ in calls_named(operations, "execute")]
    assert not any("DROP EXTENSION" in statement for statement in executed)
