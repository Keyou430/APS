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
    / "20260803_0008_phase_c_knowledge_collections.py"
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
    spec = importlib.util.spec_from_file_location("phase_c_knowledge_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_phase_c_collection_models_have_same_organization_foreign_keys() -> None:
    assert "knowledge_collections" in Base.metadata.tables
    collections = Base.metadata.tables["knowledge_collections"]
    entries = Base.metadata.tables["knowledge_entries"]

    assert {"organization_id", "parent_id", "name", "description", "sort_order"}.issubset(
        collections.c.keys()
    )
    assert "collection_id" in entries.c
    entry_foreign_keys = {
        (tuple(constraint.column_keys), constraint.referred_table.name)
        for constraint in entries.foreign_key_constraints
    }
    assert (("organization_id", "collection_id"), "knowledge_collections") in entry_foreign_keys


def test_phase_c_collection_migration_is_additive_and_reversible() -> None:
    migration = load_migration()
    operations = RecordingOperations()
    migration.op = operations

    migration.upgrade()

    assert migration.down_revision == "20260731_0007"
    assert any(
        name == "create_table" and args[0] == "knowledge_collections"
        for name, args, _kwargs in operations.calls
    )
    assert any(
        name == "add_column"
        and args[0] == "knowledge_entries"
        and args[1].name == "collection_id"
        for name, args, _kwargs in operations.calls
    )

    operations.calls.clear()
    migration.downgrade()
    assert any(
        name == "drop_column" and args[:2] == ("knowledge_entries", "collection_id")
        for name, args, _kwargs in operations.calls
    )
    assert any(
        name == "drop_table" and args[0] == "knowledge_collections"
        for name, args, _kwargs in operations.calls
    )
