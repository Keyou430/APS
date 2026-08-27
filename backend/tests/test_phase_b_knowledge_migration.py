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
    / "20260731_0007_phase_b_knowledge_productization.py"
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
    spec = importlib.util.spec_from_file_location("phase_b_knowledge_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_phase_b_models_have_fail_closed_scope_constraints() -> None:
    expected_tables = {
        "knowledge_access_grants",
        "organization_invitations",
        "organization_invitation_resources",
        "chat_session_knowledge_sources",
        "chat_turns",
        "chat_turn_citations",
    }
    assert expected_tables.issubset(Base.metadata.tables)
    entries = Base.metadata.tables["knowledge_entries"]
    sessions = Base.metadata.tables["chat_sessions"]
    retrieval_events = Base.metadata.tables["knowledge_retrieval_events"]
    assert {"visibility", "updated_at", "archived_at"}.issubset(entries.c.keys())
    assert {"surface", "knowledge_scope"}.issubset(sessions.c.keys())
    assert retrieval_events.c.chat_session_id.nullable is True
    assert {"request_kind", "retrieval_mode", "query_hmac_version"}.issubset(
        retrieval_events.c.keys()
    )


def test_phase_b_migration_backfills_surface_and_creates_security_tables() -> None:
    migration = load_migration()
    operations = RecordingOperations()
    migration.op = operations

    migration.upgrade()

    assert migration.down_revision == "20260731_0006"
    created_tables = {
        args[0] for name, args, _kwargs in operations.calls if name == "create_table"
    }
    assert {
        "knowledge_access_grants",
        "organization_invitations",
        "organization_invitation_resources",
        "chat_session_knowledge_sources",
        "chat_turns",
        "chat_turn_citations",
    } == created_tables
    executed_sql = "\n".join(
        str(args[0]) for name, args, _kwargs in operations.calls if name == "execute"
    )
    assert "hermes_backend = 'agent'" in executed_sql
    assert "THEN 'all_visible' ELSE 'none'" in executed_sql
    partial_indexes = [
        kwargs
        for name, args, kwargs in operations.calls
        if name == "create_index"
        and args[0] == "uq_knowledge_grants_active_entry_membership"
    ]
    assert len(partial_indexes) == 1
    assert partial_indexes[0]["unique"] is True
    assert "revoked_at IS NULL" in str(partial_indexes[0]["postgresql_where"])


def test_phase_b_migration_adds_visibility_before_its_constraint() -> None:
    migration = load_migration()
    operations = RecordingOperations()
    migration.op = operations

    migration.upgrade()

    visibility_column_index = next(
        index
        for index, (name, args, _kwargs) in enumerate(operations.calls)
        if name == "add_column"
        and args[0] == "knowledge_entries"
        and args[1].name == "visibility"
    )
    visibility_constraint_index = next(
        index
        for index, (name, args, _kwargs) in enumerate(operations.calls)
        if name == "create_check_constraint"
        and args[0] == "ck_knowledge_entries_visibility"
    )
    assert visibility_column_index < visibility_constraint_index


def test_phase_b_migration_downgrade_removes_only_phase_b_additions() -> None:
    migration = load_migration()
    operations = RecordingOperations()
    migration.op = operations

    migration.downgrade()

    dropped_tables = [
        args[0] for name, args, _kwargs in operations.calls if name == "drop_table"
    ]
    assert dropped_tables == [
        "chat_turn_citations",
        "chat_turns",
        "chat_session_knowledge_sources",
        "organization_invitation_resources",
        "organization_invitations",
        "knowledge_access_grants",
    ]
    assert "knowledge_entries" not in dropped_tables
    assert "chat_sessions" not in dropped_tables
