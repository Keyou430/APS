from __future__ import annotations

import importlib.util
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

from app.database import Base
from app.seed import DEFAULT_PERMISSIONS, DEFAULT_ROLE_PERMISSIONS


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "migrations"
    / "versions"
    / "20260803_0009_phase_c_organization_structure.py"
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
    spec = importlib.util.spec_from_file_location("phase_c_organization_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_phase_c_organization_models_declare_scope_constraints() -> None:
    expected = {
        "organization_units",
        "organization_positions",
        "organization_placements",
        "organization_structure_state",
    }
    assert expected.issubset(Base.metadata.tables)
    placements = Base.metadata.tables["organization_placements"]
    foreign_keys = {
        (tuple(constraint.column_keys), constraint.referred_table.name)
        for constraint in placements.foreign_key_constraints
    }
    assert (("organization_id", "membership_id"), "organization_memberships") in foreign_keys
    assert (("organization_id", "unit_id"), "organization_units") in foreign_keys
    assert (("organization_id", "position_id"), "organization_positions") in foreign_keys


def test_phase_c_permissions_are_seeded_for_internal_roles_only() -> None:
    expected = {
        "org:read",
        "portal:read",
        "portal:manage",
        "work_items:read",
        "work_items:write",
    }
    assert expected.issubset(DEFAULT_PERMISSIONS)
    assert DEFAULT_PERMISSIONS["org:admin"] == "Manage organization users, roles, and structure"
    assert {"org:read", "portal:read", "work_items:read", "work_items:write"}.issubset(
        DEFAULT_ROLE_PERMISSIONS["manager"]
    )
    assert {"org:read", "portal:read", "work_items:read", "work_items:write"}.issubset(
        DEFAULT_ROLE_PERMISSIONS["user"]
    )
    assert expected.isdisjoint(DEFAULT_ROLE_PERMISSIONS["guest"])


def test_phase_c_organization_migration_backfills_and_is_reversible() -> None:
    migration = load_migration()
    operations = RecordingOperations()
    migration.op = operations

    migration.upgrade()

    assert migration.down_revision == "20260803_0008"
    created = {
        args[0] for name, args, _kwargs in operations.calls if name == "create_table"
    }
    assert {
        "organization_units",
        "organization_positions",
        "organization_placements",
        "organization_structure_state",
    } == created
    executed = "\n".join(
        str(args[0]) for name, args, _kwargs in operations.calls if name == "execute"
    )
    assert "organization_memberships" in executed
    assert "member_type = 'internal'" in executed
    assert "organization_structure_state" in executed

    operations.calls.clear()
    migration.downgrade()
    dropped = [
        args[0] for name, args, _kwargs in operations.calls if name == "drop_table"
    ]
    assert dropped == [
        "organization_placements",
        "organization_positions",
        "organization_structure_state",
        "organization_units",
    ]
