"""add chat turn web sources for platform-validated web evidence

Revision ID: 20260823_0020
Revises: 20260820_0019
Create Date: 2026-08-23
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260823_0020"
down_revision: str | None = "20260820_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_turn_web_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column(
            "chat_turn_id",
            sa.Integer(),
            sa.ForeignKey("chat_turns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("searched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_id", sa.String(length=160), nullable=True),
        sa.Column("query", sa.String(length=500), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "chat_turn_id", "ordinal", name="uq_chat_turn_web_sources_turn_ordinal"
        ),
        sa.UniqueConstraint(
            "organization_id", "id", name="uq_chat_turn_web_sources_org_id"
        ),
    )
    op.create_index(
        "ix_chat_turn_web_sources_organization_id",
        "chat_turn_web_sources",
        ["organization_id"],
    )
    op.create_index(
        "ix_chat_turn_web_sources_chat_turn_id", "chat_turn_web_sources", ["chat_turn_id"]
    )
    op.create_index(
        "ix_chat_turn_web_sources_correlation_id",
        "chat_turn_web_sources",
        ["correlation_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_chat_turn_web_sources_correlation_id", table_name="chat_turn_web_sources"
    )
    op.drop_index(
        "ix_chat_turn_web_sources_chat_turn_id", table_name="chat_turn_web_sources"
    )
    op.drop_index(
        "ix_chat_turn_web_sources_organization_id", table_name="chat_turn_web_sources"
    )
    op.drop_table("chat_turn_web_sources")
