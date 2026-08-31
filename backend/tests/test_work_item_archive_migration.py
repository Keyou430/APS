import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from app.database import Base

MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "migrations"
    / "versions"
    / "20260817_0018_work_item_week_archive.py"
)


def test_work_item_archive_migration_is_the_linear_head_and_backfills_safely() -> None:
    assert MIGRATION_PATH.exists(), f"Missing migration: {MIGRATION_PATH}"
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'revision: str = "20260817_0018"' in source
    assert 'down_revision: str | None = "20260815_0017"' in source
    assert 'server_default="week"' in source
    assert 'server_default="day"' in source
    assert "postgresql_where" in source
    assert "sqlite_where" in source


def test_migrations_upgrade_a_fresh_sqlite_database_to_head(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "migration.db"
    environment = os.environ.copy()
    environment["DATABASE_URL"] = f"sqlite+aiosqlite:///{database_path.as_posix()}"

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=MIGRATION_PATH.parents[2],
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0, result.stderr
    with sqlite3.connect(database_path) as connection:
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        table_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'work_items'"
        ).fetchone()
        columns = {
            row[1]: row[4]
            for row in connection.execute("PRAGMA table_info('work_items')").fetchall()
        }
        pipeline_task_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info('pipeline_tasks')").fetchall()
        }
        decision_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info('dashboard_decisions')").fetchall()
        }
        pipeline_run_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info('pipeline_runs')").fetchall()
        }

    assert version == ("20260827_0024",)
    assert table_sql is not None
    assert "ck_work_items_task_scope" in table_sql[0]
    assert columns["task_scope"] == "'day'"
    assert {
        "approval_required",
        "approval_assignee_type",
        "approval_assignee_id",
        "approval_role_name",
    }.issubset(pipeline_task_columns)
    assert {
        "approver_user_id",
        "approval_comment",
        "rejection_reason",
        "reason_type",
        "decided_at",
    }.issubset(decision_columns)
    assert "prompt_override" in pipeline_run_columns


def test_work_item_model_exposes_traceable_archive_fields_and_due_index() -> None:
    table = Base.metadata.tables["work_items"]
    assert {
        "task_scope",
        "archive_timezone",
        "archive_after",
        "original_scope",
        "original_due_at",
        "archived_at",
        "archive_reason",
        "archive_batch_id",
        "week_key",
    }.issubset(table.c.keys())
    archive_index = next(
        index for index in table.indexes if index.name == "ix_work_items_day_archive_due"
    )
    assert [column.name for column in archive_index.columns] == ["archive_after", "id"]
    assert archive_index.dialect_options["postgresql"]["where"] is not None
