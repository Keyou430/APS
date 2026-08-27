"""Initial Hermes platform schema.

Revision ID: 20260717_0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260717_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(50), nullable=False, unique=True),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_roles_name", "roles", ["name"], unique=True)
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(80), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_role_id", "users", ["role_id"])
    op.create_index("ix_users_is_active", "users", ["is_active"])

    def user_table(name: str, *columns: sa.Column, unique_user: bool = False) -> None:
        op.create_table(
            name,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
                unique=unique_user,
            ),
            *columns,
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index(f"ix_{name}_user_id", name, ["user_id"])

    user_table(
        "refresh_tokens",
        sa.Column("jti", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_refresh_tokens_jti", "refresh_tokens", ["jti"], unique=True)
    user_table(
        "hermes_profiles",
        sa.Column("profile_name", sa.String(100), nullable=False, unique=True),
        sa.Column("hermes_home", sa.String(500), nullable=False, unique=True),
        sa.Column("port", sa.Integer(), nullable=False, unique=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="stopped"),
        unique_user=True,
    )
    user_table(
        "knowledge_entries",
        sa.Column("type", sa.String(30), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("url", sa.String(2048)),
        sa.Column("content", sa.Text()),
        sa.Column("file_path", sa.String(500)),
    )
    op.create_index("ix_knowledge_entries_type", "knowledge_entries", ["type"])
    user_table(
        "skills",
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_ai_generated", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_skills_category", "skills", ["category"])
    user_table(
        "reminders",
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("type", sa.String(20), nullable=False, server_default="one-time"),
        sa.Column("recurrence", sa.String(20)),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("notification_channel", sa.String(20), nullable=False, server_default="in-app"),
    )
    op.create_index("ix_reminders_due_date", "reminders", ["due_date"])
    op.create_index("ix_reminders_status", "reminders", ["status"])
    user_table(
        "chat_sessions",
        sa.Column("hermes_session_id", sa.String(100), nullable=False, unique=True),
        sa.Column("title", sa.String(255), nullable=False, server_default="New conversation"),
    )
    op.create_index(
        "ix_chat_sessions_hermes_session_id", "chat_sessions", ["hermes_session_id"], unique=True
    )


def downgrade() -> None:
    for table in (
        "chat_sessions",
        "reminders",
        "skills",
        "knowledge_entries",
        "hermes_profiles",
        "refresh_tokens",
        "users",
        "roles",
    ):
        op.drop_table(table)
