from __future__ import annotations

import importlib.util
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

from app.database import Base


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "migrations"
    / "versions"
    / "20260811_0013_phase_d_memory.py"
)


class RecordingOperations:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    def get_bind(self):
        return self.bind

    @contextmanager
    def batch_alter_table(self, *args: Any, **kwargs: Any):
        self.calls.append(("batch_alter_table", args, kwargs))
        yield self

    def __getattr__(self, name: str):
        def record(*args: Any, **kwargs: Any) -> None:
            self.calls.append((name, args, kwargs))

        return record


def load_migration() -> ModuleType:
    assert MIGRATION_PATH.exists(), f"Missing migration: {MIGRATION_PATH}"
    spec = importlib.util.spec_from_file_location("phase_d_memory_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_phase_d_memory_models_declare_authorized_ledger_schema() -> None:
    expected_tables = {
        "memory_capture_sources",
        "memory_records",
        "memory_versions",
        "memory_source_links",
        "memory_extraction_jobs",
        "memory_embedding_jobs",
        "memory_retrieval_events",
    }
    assert expected_tables.issubset(Base.metadata.tables)

    records = Base.metadata.tables["memory_records"]
    assert {
        "memory_id",
        "organization_id",
        "user_id",
        "content",
        "type",
        "layer",
        "status",
        "origin",
        "revision",
        "embedding",
        "embedding_model",
        "embedding_version",
        "embedding_state",
        "updated_at",
    }.issubset(records.c.keys())
    assert "memory_mode" in Base.metadata.tables["chat_sessions"].c
    assert "source_content_sha256" in Base.metadata.tables["memory_source_links"].c

    expected_foreign_keys = {
        "memory_capture_sources": {
            ("organization_id", "user_id"),
            ("organization_id", "chat_session_id"),
            ("organization_id", "chat_turn_id"),
        },
        "memory_records": {
            ("organization_id", "user_id"),
            ("organization_id", "user_id", "supersedes_memory_id"),
        },
        "memory_versions": {("organization_id", "user_id", "memory_id")},
        "memory_source_links": {
            ("organization_id", "user_id", "memory_id"),
            ("organization_id", "user_id", "source_id"),
        },
        "memory_extraction_jobs": {("organization_id", "user_id", "source_id")},
        "memory_embedding_jobs": {("organization_id", "user_id", "memory_id")},
        "memory_retrieval_events": {
            ("organization_id", "user_id"),
            ("organization_id", "chat_session_id"),
        },
    }
    for table_name, expected in expected_foreign_keys.items():
        table = Base.metadata.tables[table_name]
        actual = {tuple(column.name for column in constraint.columns) for constraint in table.foreign_key_constraints}
        assert expected <= actual, table_name

    records_org_user_fk = next(
        constraint
        for constraint in records.foreign_key_constraints
        if constraint.name == "fk_memory_records_org_user"
    )
    assert records_org_user_fk.ondelete == "RESTRICT", (
        "master §7.4/R9：Memory user FK 必须为 RESTRICT，账号删除服务先受控清理"
    )
    record_checks = {constraint.name for constraint in records.constraints}
    assert "ck_memory_records_embedding_state" in record_checks
    jobs = Base.metadata.tables["memory_embedding_jobs"]
    job_checks = {constraint.name for constraint in jobs.constraints}
    assert "ck_memory_embedding_jobs_status" in job_checks
    assert "revision" in jobs.c.keys()

    indexes = Base.metadata.tables["memory_records"].indexes
    active_owner = next(index for index in indexes if index.name == "ix_memory_records_active_owner_list")
    assert [column.name for column in active_owner.columns] == [
        "organization_id",
        "user_id",
        "updated_at",
        "memory_id",
    ]
    assert str(active_owner.dialect_options["postgresql"].get("where")) == "status = 'active'"
    assert str(active_owner.dialect_options["sqlite"].get("where")) == "status = 'active'"


def test_phase_d_memory_migration_is_additive_scoped_and_reversible() -> None:
    migration = load_migration()
    assert migration.revision == "20260811_0013"
    assert migration.down_revision == "20260810_0012"

    operations = RecordingOperations()
    migration.op = operations
    migration.upgrade()

    created_tables = {
        args[0] for name, args, _kwargs in operations.calls if name == "create_table"
    }
    assert created_tables == {
        "memory_capture_sources",
        "memory_records",
        "memory_versions",
        "memory_source_links",
        "memory_extraction_jobs",
        "memory_embedding_jobs",
        "memory_retrieval_events",
    }
    created_indexes = {
        args[0] for name, args, _kwargs in operations.calls if name == "create_index"
    }
    assert {
        "ix_memory_records_active_owner_list",
        "ix_memory_records_active_fts",
        "ix_memory_records_active_embedding_hnsw",
        "ix_memory_extraction_jobs_claim",
        "ix_memory_embedding_jobs_claim",
    }.issubset(created_indexes)

    operations.calls.clear()
    migration.downgrade()
    dropped_tables = [
        args[0] for name, args, _kwargs in operations.calls if name == "drop_table"
    ]
    assert dropped_tables == [
        "memory_retrieval_events",
        "memory_extraction_jobs",
        "memory_source_links",
        "memory_versions",
        "memory_embedding_jobs",
        "memory_records",
        "memory_capture_sources",
    ]
