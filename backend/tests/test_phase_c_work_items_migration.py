from __future__ import annotations

import importlib.util
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

from app.database import Base


MIGRATION_PATH = Path(__file__).parents[1] / "migrations" / "versions" / "20260803_0011_phase_c_work_items_dashboard_layouts.py"


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
    spec = importlib.util.spec_from_file_location("phase_c_work_items_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_work_item_and_layout_models_declare_same_organization_constraints() -> None:
    assert {"work_items", "work_item_events", "dashboard_layouts"}.issubset(Base.metadata.tables)
    events = Base.metadata.tables["work_item_events"]
    event_foreign_keys = {
        (tuple(constraint.column_keys), constraint.referred_table.name)
        for constraint in events.foreign_key_constraints
    }
    assert (("organization_id", "work_item_id"), "work_items") in event_foreign_keys
    layouts = Base.metadata.tables["dashboard_layouts"]
    assert {"organization_id", "user_id", "layouts", "revision"}.issubset(layouts.c.keys())


def test_phase_c_work_item_migration_is_additive_and_reversible() -> None:
    migration = load_migration()
    operations = RecordingOperations()
    migration.op = operations
    migration.upgrade()
    assert migration.down_revision == "20260803_0010"
    assert {args[0] for name, args, _kwargs in operations.calls if name == "create_table"} == {
        "work_items", "work_item_events", "dashboard_layouts"
    }
    operations.calls.clear()
    migration.downgrade()
    assert [args[0] for name, args, _kwargs in operations.calls if name == "drop_table"] == [
        "dashboard_layouts", "work_item_events", "work_items"
    ]
