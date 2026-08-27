"""Add Phase C portal announcements and read state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260803_0010"
down_revision: str | None = "20260803_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ANNOUNCEMENT_INDEX_COLUMNS = (
    "organization_id",
    "author_user_id",
    "priority",
    "status",
    "is_pinned",
    "published_at",
)


def upgrade() -> None:
    op.create_table(
        "portal_announcements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("summary", sa.String(500), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("priority", sa.String(20), nullable=False, server_default="normal"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "organization_id", "id", name="uq_portal_announcements_org_id"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "author_user_id"],
            [
                "organization_memberships.organization_id",
                "organization_memberships.user_id",
            ],
            ondelete="RESTRICT",
            name="fk_portal_announcements_org_author",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'withdrawn')",
            name="ck_portal_announcements_status",
        ),
        sa.CheckConstraint(
            "priority IN ('normal', 'important')",
            name="ck_portal_announcements_priority",
        ),
    )
    for column in ANNOUNCEMENT_INDEX_COLUMNS:
        op.create_index(
            f"ix_portal_announcements_{column}",
            "portal_announcements",
            [column],
        )

    op.create_table(
        "portal_announcement_reads",
        sa.Column("announcement_id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column(
            "read_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "announcement_id"],
            ["portal_announcements.organization_id", "portal_announcements.id"],
            ondelete="CASCADE",
            name="fk_portal_reads_org_announcement",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "user_id"],
            [
                "organization_memberships.organization_id",
                "organization_memberships.user_id",
            ],
            ondelete="CASCADE",
            name="fk_portal_reads_org_user",
        ),
    )
    op.create_index(
        "ix_portal_announcement_reads_organization_id",
        "portal_announcement_reads",
        ["organization_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_portal_announcement_reads_organization_id",
        table_name="portal_announcement_reads",
    )
    op.drop_table("portal_announcement_reads")
    for column in reversed(ANNOUNCEMENT_INDEX_COLUMNS):
        op.drop_index(
            f"ix_portal_announcements_{column}",
            table_name="portal_announcements",
        )
    op.drop_table("portal_announcements")
