"""archive overdue daily work items into weekly scope

Revision ID: 20260817_0018
Revises: 20260815_0017
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260817_0018"
down_revision: str | None = "20260815_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ARCHIVE_DUE_PREDICATE = sa.text(
    "task_scope = 'day' AND archived_at IS NULL AND archive_after IS NOT NULL "
    "AND status IN ('pending', 'in_progress')"
)


def upgrade() -> None:
    # Existing tasks predate daily semantics, so preserve them as weekly tasks.
    op.add_column(
        "work_items",
        sa.Column("task_scope", sa.String(length=10), server_default="week", nullable=False),
    )
    op.add_column(
        "work_items",
        sa.Column(
            "archive_timezone",
            sa.String(length=80),
            server_default="Asia/Shanghai",
            nullable=False,
        ),
    )
    op.add_column(
        "work_items", sa.Column("archive_after", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "work_items", sa.Column("original_scope", sa.String(length=10), nullable=True)
    )
    op.add_column(
        "work_items", sa.Column("original_due_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "work_items", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "work_items", sa.Column("archive_reason", sa.String(length=30), nullable=True)
    )
    op.add_column(
        "work_items", sa.Column("archive_batch_id", sa.String(length=36), nullable=True)
    )
    op.add_column("work_items", sa.Column("week_key", sa.String(length=10), nullable=True))

    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("work_items", recreate="always") as batch:
            batch.create_check_constraint(
                "ck_work_items_task_scope", "task_scope IN ('day', 'week')"
            )
            batch.create_check_constraint(
                "ck_work_items_original_scope",
                "original_scope IS NULL OR original_scope IN ('day', 'week')",
            )
            batch.create_check_constraint(
                "ck_work_items_archive_reason",
                "archive_reason IS NULL OR archive_reason IN ('overdue')",
            )
            batch.create_check_constraint(
                "ck_work_items_archive_trace",
                "archived_at IS NULL OR ("
                "task_scope = 'week' AND original_scope = 'day' "
                "AND original_due_at IS NOT NULL AND archive_reason = 'overdue' "
                "AND archive_batch_id IS NOT NULL AND week_key IS NOT NULL)",
            )
            batch.create_check_constraint(
                "ck_work_items_archive_after_scope",
                "(task_scope = 'day' AND archived_at IS NULL) OR archive_after IS NULL",
            )
            batch.alter_column(
                "task_scope",
                existing_type=sa.String(length=10),
                existing_nullable=False,
                server_default="day",
            )
    else:
        op.create_check_constraint(
            "ck_work_items_task_scope", "work_items", "task_scope IN ('day', 'week')"
        )
        op.create_check_constraint(
            "ck_work_items_original_scope",
            "work_items",
            "original_scope IS NULL OR original_scope IN ('day', 'week')",
        )
        op.create_check_constraint(
            "ck_work_items_archive_reason",
            "work_items",
            "archive_reason IS NULL OR archive_reason IN ('overdue')",
        )
        op.create_check_constraint(
            "ck_work_items_archive_trace",
            "work_items",
            "archived_at IS NULL OR ("
            "task_scope = 'week' AND original_scope = 'day' "
            "AND original_due_at IS NOT NULL AND archive_reason = 'overdue' "
            "AND archive_batch_id IS NOT NULL AND week_key IS NOT NULL)",
        )
        op.create_check_constraint(
            "ck_work_items_archive_after_scope",
            "work_items",
            "(task_scope = 'day' AND archived_at IS NULL) OR archive_after IS NULL",
        )
        op.alter_column("work_items", "task_scope", server_default="day")

    op.create_index(
        "ix_work_items_day_archive_due",
        "work_items",
        ["archive_after", "id"],
        unique=False,
        postgresql_where=ARCHIVE_DUE_PREDICATE,
        sqlite_where=ARCHIVE_DUE_PREDICATE,
    )


def downgrade() -> None:
    op.drop_index("ix_work_items_day_archive_due", table_name="work_items")
    constraints = (
        "ck_work_items_archive_after_scope",
        "ck_work_items_archive_trace",
        "ck_work_items_archive_reason",
        "ck_work_items_original_scope",
        "ck_work_items_task_scope",
    )
    columns = (
        "week_key",
        "archive_batch_id",
        "archive_reason",
        "archived_at",
        "original_due_at",
        "original_scope",
        "archive_after",
        "archive_timezone",
        "task_scope",
    )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("work_items", recreate="always") as batch:
            for constraint_name in constraints:
                batch.drop_constraint(constraint_name, type_="check")
            for column_name in columns:
                batch.drop_column(column_name)
    else:
        for constraint_name in constraints:
            op.drop_constraint(constraint_name, "work_items", type_="check")
        for column_name in columns:
            op.drop_column("work_items", column_name)
