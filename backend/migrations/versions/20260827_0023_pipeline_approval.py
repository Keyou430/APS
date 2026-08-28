"""Add pipeline approval policy and decision audit fields."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260827_0023"
down_revision: str | None = "20260823_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _approval_required_column() -> sa.Column:
    return sa.Column(
        "approval_required",
        sa.Boolean(),
        nullable=False,
        server_default=sa.true(),
    )


def _upgrade_sqlite() -> None:
    with op.batch_alter_table("pipeline_tasks", recreate="always") as batch:
        batch.add_column(_approval_required_column())
        batch.add_column(
            sa.Column(
                "approval_assignee_type",
                sa.String(length=20),
                nullable=False,
                server_default="creator",
            )
        )
        batch.add_column(sa.Column("approval_assignee_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("approval_role_name", sa.String(length=50), nullable=True))
        batch.add_column(
            sa.Column("approval_reminder_after_minutes", sa.Integer(), nullable=True)
        )
        batch.add_column(
            sa.Column("approval_escalation_after_minutes", sa.Integer(), nullable=True)
        )
        batch.add_column(
            sa.Column("approval_escalation_role_name", sa.String(length=50), nullable=True)
        )
        batch.create_index(
            "ix_pipeline_tasks_approval_assignee_id", ["approval_assignee_id"]
        )
        batch.create_check_constraint(
            "ck_pipeline_tasks_approval_assignee_type",
            "approval_assignee_type IN ('creator', 'member', 'role')",
        )
        batch.create_check_constraint(
            "ck_pipeline_tasks_approval_member_consistency",
            "(approval_assignee_type = 'member' AND approval_assignee_id IS NOT NULL) OR "
            "(approval_assignee_type != 'member' AND approval_assignee_id IS NULL)",
        )
        batch.create_check_constraint(
            "ck_pipeline_tasks_approval_role_consistency",
            "(approval_assignee_type = 'role' AND approval_role_name IS NOT NULL) OR "
            "(approval_assignee_type != 'role' AND approval_role_name IS NULL)",
        )
        batch.create_foreign_key(
            "fk_pipeline_tasks_approval_assignee",
            "users",
            ["approval_assignee_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    with op.batch_alter_table("dashboard_decisions", recreate="always") as batch:
        batch.add_column(sa.Column("approver_user_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("approval_comment", sa.Text(), nullable=True))
        batch.add_column(sa.Column("rejection_reason", sa.Text(), nullable=True))
        batch.add_column(sa.Column("reason_type", sa.String(length=20), nullable=True))
        batch.add_column(sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(
            sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(
            sa.Column("escalation_sent_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.create_index(
            "ix_dashboard_decisions_approver_user_id", ["approver_user_id"]
        )
        batch.create_index("ix_dashboard_decisions_decided_at", ["decided_at"])
        batch.create_index(
            "ix_dashboard_decisions_pending_reminders", ["status", "created_at", "id"]
        )
        batch.create_check_constraint(
            "ck_dashboard_decisions_reason_type",
            "reason_type IS NULL OR reason_type IN ('no_need', 'other', 'regenerate')",
        )
        batch.create_foreign_key(
            "fk_dashboard_decisions_approver_user",
            "users",
            ["approver_user_id"],
            ["id"],
            ondelete="SET NULL",
        )


def _upgrade_standard() -> None:
    op.add_column("pipeline_tasks", _approval_required_column())
    op.add_column(
        "pipeline_tasks",
        sa.Column(
            "approval_assignee_type",
            sa.String(length=20),
            nullable=False,
            server_default="creator",
        ),
    )
    op.add_column(
        "pipeline_tasks", sa.Column("approval_assignee_id", sa.Integer(), nullable=True)
    )
    op.add_column(
        "pipeline_tasks", sa.Column("approval_role_name", sa.String(length=50), nullable=True)
    )
    op.add_column(
        "pipeline_tasks",
        sa.Column("approval_reminder_after_minutes", sa.Integer(), nullable=True),
    )
    op.add_column(
        "pipeline_tasks",
        sa.Column("approval_escalation_after_minutes", sa.Integer(), nullable=True),
    )
    op.add_column(
        "pipeline_tasks",
        sa.Column("approval_escalation_role_name", sa.String(length=50), nullable=True),
    )
    op.create_index(
        "ix_pipeline_tasks_approval_assignee_id",
        "pipeline_tasks",
        ["approval_assignee_id"],
    )
    op.create_check_constraint(
        "ck_pipeline_tasks_approval_assignee_type",
        "pipeline_tasks",
        "approval_assignee_type IN ('creator', 'member', 'role')",
    )
    op.create_check_constraint(
        "ck_pipeline_tasks_approval_member_consistency",
        "pipeline_tasks",
        "(approval_assignee_type = 'member' AND approval_assignee_id IS NOT NULL) OR "
        "(approval_assignee_type != 'member' AND approval_assignee_id IS NULL)",
    )
    op.create_check_constraint(
        "ck_pipeline_tasks_approval_role_consistency",
        "pipeline_tasks",
        "(approval_assignee_type = 'role' AND approval_role_name IS NOT NULL) OR "
        "(approval_assignee_type != 'role' AND approval_role_name IS NULL)",
    )
    op.create_foreign_key(
        "fk_pipeline_tasks_approval_assignee",
        "pipeline_tasks",
        "users",
        ["approval_assignee_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.add_column(
        "dashboard_decisions", sa.Column("approver_user_id", sa.Integer(), nullable=True)
    )
    op.add_column(
        "dashboard_decisions", sa.Column("approval_comment", sa.Text(), nullable=True)
    )
    op.add_column(
        "dashboard_decisions", sa.Column("rejection_reason", sa.Text(), nullable=True)
    )
    op.add_column(
        "dashboard_decisions",
        sa.Column("reason_type", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "dashboard_decisions",
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "dashboard_decisions",
        sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "dashboard_decisions",
        sa.Column("escalation_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_dashboard_decisions_approver_user_id",
        "dashboard_decisions",
        ["approver_user_id"],
    )
    op.create_index(
        "ix_dashboard_decisions_decided_at", "dashboard_decisions", ["decided_at"]
    )
    op.create_index(
        "ix_dashboard_decisions_pending_reminders",
        "dashboard_decisions",
        ["status", "created_at", "id"],
    )
    op.create_check_constraint(
        "ck_dashboard_decisions_reason_type",
        "dashboard_decisions",
        "reason_type IS NULL OR reason_type IN ('no_need', 'other', 'regenerate')",
    )
    op.create_foreign_key(
        "fk_dashboard_decisions_approver_user",
        "dashboard_decisions",
        "users",
        ["approver_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        _upgrade_sqlite()
    else:
        _upgrade_standard()


def _downgrade_sqlite() -> None:
    with op.batch_alter_table("dashboard_decisions", recreate="always") as batch:
        batch.drop_constraint(
            "fk_dashboard_decisions_approver_user", type_="foreignkey"
        )
        batch.drop_constraint("ck_dashboard_decisions_reason_type", type_="check")
        batch.drop_index("ix_dashboard_decisions_pending_reminders")
        batch.drop_index("ix_dashboard_decisions_decided_at")
        batch.drop_index("ix_dashboard_decisions_approver_user_id")
        for column in (
            "escalation_sent_at",
            "reminder_sent_at",
            "decided_at",
            "reason_type",
            "rejection_reason",
            "approval_comment",
            "approver_user_id",
        ):
            batch.drop_column(column)

    with op.batch_alter_table("pipeline_tasks", recreate="always") as batch:
        batch.drop_constraint("fk_pipeline_tasks_approval_assignee", type_="foreignkey")
        batch.drop_constraint(
            "ck_pipeline_tasks_approval_role_consistency", type_="check"
        )
        batch.drop_constraint(
            "ck_pipeline_tasks_approval_member_consistency", type_="check"
        )
        batch.drop_constraint("ck_pipeline_tasks_approval_assignee_type", type_="check")
        batch.drop_index("ix_pipeline_tasks_approval_assignee_id")
        for column in (
            "approval_escalation_role_name",
            "approval_escalation_after_minutes",
            "approval_reminder_after_minutes",
            "approval_role_name",
            "approval_assignee_id",
            "approval_assignee_type",
            "approval_required",
        ):
            batch.drop_column(column)


def _downgrade_standard() -> None:
    op.drop_constraint(
        "fk_dashboard_decisions_approver_user",
        "dashboard_decisions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_dashboard_decisions_reason_type", "dashboard_decisions", type_="check"
    )
    op.drop_index(
        "ix_dashboard_decisions_pending_reminders", table_name="dashboard_decisions"
    )
    op.drop_index("ix_dashboard_decisions_decided_at", table_name="dashboard_decisions")
    op.drop_index(
        "ix_dashboard_decisions_approver_user_id", table_name="dashboard_decisions"
    )
    for column in (
        "escalation_sent_at",
        "reminder_sent_at",
        "decided_at",
        "reason_type",
        "rejection_reason",
        "approval_comment",
        "approver_user_id",
    ):
        op.drop_column("dashboard_decisions", column)

    op.drop_constraint(
        "fk_pipeline_tasks_approval_assignee", "pipeline_tasks", type_="foreignkey"
    )
    op.drop_constraint(
        "ck_pipeline_tasks_approval_role_consistency", "pipeline_tasks", type_="check"
    )
    op.drop_constraint(
        "ck_pipeline_tasks_approval_member_consistency", "pipeline_tasks", type_="check"
    )
    op.drop_constraint(
        "ck_pipeline_tasks_approval_assignee_type", "pipeline_tasks", type_="check"
    )
    op.drop_index("ix_pipeline_tasks_approval_assignee_id", table_name="pipeline_tasks")
    for column in (
        "approval_escalation_role_name",
        "approval_escalation_after_minutes",
        "approval_reminder_after_minutes",
        "approval_role_name",
        "approval_assignee_id",
        "approval_assignee_type",
        "approval_required",
    ):
        op.drop_column("pipeline_tasks", column)


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        _downgrade_sqlite()
    else:
        _downgrade_standard()
