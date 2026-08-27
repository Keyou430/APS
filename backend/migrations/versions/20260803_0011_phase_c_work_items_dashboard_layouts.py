"""Add Phase C work items, events, and dashboard layouts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260803_0011"
down_revision: str | None = "20260803_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "work_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("assignee_membership_id", sa.Integer(), nullable=False),
        sa.Column("created_by_membership_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("priority", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("origin", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("source_ref", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "id", name="uq_work_items_org_id"),
        sa.ForeignKeyConstraint(
            ["organization_id", "assignee_membership_id"],
            ["organization_memberships.organization_id", "organization_memberships.id"],
            ondelete="RESTRICT",
            name="fk_work_items_org_assignee",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "created_by_membership_id"],
            ["organization_memberships.organization_id", "organization_memberships.id"],
            ondelete="RESTRICT",
            name="fk_work_items_org_creator",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'in_progress', 'completed', 'cancelled')",
            name="ck_work_items_status",
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'medium', 'high')",
            name="ck_work_items_priority",
        ),
        sa.CheckConstraint(
            "origin IN ('manual', 'reminder', 'chat', 'agent')",
            name="ck_work_items_origin",
        ),
    )
    for column in (
        "organization_id", "assignee_membership_id", "created_by_membership_id",
        "status", "priority", "due_at", "origin",
    ):
        op.create_index(f"ix_work_items_{column}", "work_items", [column])

    op.create_table(
        "work_item_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("work_item_id", sa.Integer(), nullable=False),
        sa.Column("actor_membership_id", sa.Integer(), nullable=False),
        sa.Column("from_status", sa.String(20), nullable=True),
        sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["organization_id", "work_item_id"],
            ["work_items.organization_id", "work_items.id"],
            ondelete="CASCADE",
            name="fk_work_item_events_org_item",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "actor_membership_id"],
            ["organization_memberships.organization_id", "organization_memberships.id"],
            ondelete="RESTRICT",
            name="fk_work_item_events_org_actor",
        ),
    )
    for column in ("organization_id", "work_item_id", "actor_membership_id", "occurred_at"):
        op.create_index(f"ix_work_item_events_{column}", "work_item_events", [column])

    op.create_table(
        "dashboard_layouts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("layouts", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "organization_id", "user_id", name="uq_dashboard_layouts_org_user"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["organization_memberships.organization_id", "organization_memberships.user_id"],
            ondelete="CASCADE",
            name="fk_dashboard_layouts_org_user",
        ),
    )
    op.create_index("ix_dashboard_layouts_organization_id", "dashboard_layouts", ["organization_id"])
    op.create_index("ix_dashboard_layouts_user_id", "dashboard_layouts", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_dashboard_layouts_user_id", table_name="dashboard_layouts")
    op.drop_index("ix_dashboard_layouts_organization_id", table_name="dashboard_layouts")
    op.drop_table("dashboard_layouts")
    for column in reversed(("organization_id", "work_item_id", "actor_membership_id", "occurred_at")):
        op.drop_index(f"ix_work_item_events_{column}", table_name="work_item_events")
    op.drop_table("work_item_events")
    for column in reversed((
        "organization_id", "assignee_membership_id", "created_by_membership_id",
        "status", "priority", "due_at", "origin",
    )):
        op.drop_index(f"ix_work_items_{column}", table_name="work_items")
    op.drop_table("work_items")
