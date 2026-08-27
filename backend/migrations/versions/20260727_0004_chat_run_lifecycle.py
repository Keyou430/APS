"""Add platform-owned active Hermes run lifecycle state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260727_0004"
down_revision: str | None = "20260724_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chat_sessions",
        sa.Column("active_hermes_run_id", sa.String(100), nullable=True),
    )
    op.add_column(
        "chat_sessions",
        sa.Column("active_run_status", sa.String(30), nullable=True),
    )
    op.create_index(
        "ix_chat_sessions_active_hermes_run_id",
        "chat_sessions",
        ["active_hermes_run_id"],
        unique=True,
    )
    op.create_index(
        "ix_chat_sessions_active_run_status",
        "chat_sessions",
        ["active_run_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_chat_sessions_active_run_status", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_active_hermes_run_id", table_name="chat_sessions")
    op.drop_column("chat_sessions", "active_run_status")
    op.drop_column("chat_sessions", "active_hermes_run_id")
