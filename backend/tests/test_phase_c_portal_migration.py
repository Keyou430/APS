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
    / "20260803_0010_phase_c_portal_content.py"
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
    spec = importlib.util.spec_from_file_location("phase_c_portal_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_phase_c_portal_models_scope_announcement_reads_to_same_organization() -> None:
    expected = {"portal_announcements", "portal_announcement_reads"}
    assert expected.issubset(Base.metadata.tables)
    reads = Base.metadata.tables["portal_announcement_reads"]
    foreign_keys = {
        (tuple(constraint.column_keys), constraint.referred_table.name)
        for constraint in reads.foreign_key_constraints
    }
    assert (("organization_id", "announcement_id"), "portal_announcements") in foreign_keys
    assert (("organization_id", "user_id"), "organization_memberships") in foreign_keys


def test_phase_c_portal_migration_is_additive_and_reversible() -> None:
    migration = load_migration()
    operations = RecordingOperations()
    migration.op = operations

    migration.upgrade()

    assert migration.down_revision == "20260803_0009"
    created = {args[0] for name, args, _kwargs in operations.calls if name == "create_table"}
    assert created == {"portal_announcements", "portal_announcement_reads"}

    operations.calls.clear()
    migration.downgrade()
    dropped = [args[0] for name, args, _kwargs in operations.calls if name == "drop_table"]
    assert dropped == ["portal_announcement_reads", "portal_announcements"]
