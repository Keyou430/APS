"""add explicit knowledge entry enabled state

Revision ID: 20260820_0019
Revises: 20260817_0018
Create Date: 2026-08-20
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260820_0019"
down_revision: str | None = "20260817_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_entries",
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.create_index(
        "ix_knowledge_entries_enabled", "knowledge_entries", ["enabled"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_entries_enabled", table_name="knowledge_entries")
    op.drop_column("knowledge_entries", "enabled")
