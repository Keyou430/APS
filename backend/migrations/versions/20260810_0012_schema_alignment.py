"""Align legacy nullable columns and idempotency indexes with the ORM contract."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260810_0012"
down_revision: str | None = "20260803_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


LEGACY_TIMESTAMP_TABLES = (
    "organizations",
    "roles",
    "permissions",
    "users",
    "organization_memberships",
    "audit_events",
    "refresh_tokens",
    "channel_identities",
    "delivery_targets",
    "routing_rules",
    "run_correlations",
    "delivery_outbox",
    "hermes_profiles",
    "knowledge_entries",
    "skills",
    "reminders",
    "chat_sessions",
)


def _set_created_at_not_null(table_name: str) -> None:
    bind = op.get_bind()
    table = sa.table(
        table_name,
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    bind.execute(
        sa.update(table)
        .where(table.c.created_at.is_(None))
        .values(created_at=sa.func.now())
    )
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(table_name, recreate="always") as batch:
            batch.alter_column(
                "created_at",
                existing_type=sa.DateTime(timezone=True),
                nullable=False,
            )
    else:
        op.alter_column(
            table_name,
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )


def _set_refresh_token_organization_not_null() -> None:
    bind = op.get_bind()
    refresh_tokens = sa.table(
        "refresh_tokens",
        sa.column("id", sa.Integer()),
        sa.column("user_id", sa.Integer()),
        sa.column("organization_id", sa.Integer()),
    )
    users = sa.table(
        "users",
        sa.column("id", sa.Integer()),
        sa.column("default_organization_id", sa.Integer()),
    )
    bind.execute(
        sa.update(refresh_tokens)
        .where(refresh_tokens.c.organization_id.is_(None))
        .values(
            organization_id=sa.select(users.c.default_organization_id)
            .where(users.c.id == refresh_tokens.c.user_id)
            .scalar_subquery()
        )
    )
    # Tokens without a surviving user organization cannot be used safely.
    bind.execute(
        sa.delete(refresh_tokens).where(refresh_tokens.c.organization_id.is_(None))
    )
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("refresh_tokens", recreate="always") as batch:
            batch.alter_column(
                "organization_id",
                existing_type=sa.Integer(),
                nullable=False,
            )
    else:
        op.alter_column(
            "refresh_tokens",
            "organization_id",
            existing_type=sa.Integer(),
            nullable=False,
        )


def _replace_idempotency_indexes() -> None:
    for table_name in ("run_correlations", "delivery_outbox"):
        index_name = f"ix_{table_name}_idempotency_key"
        op.drop_index(index_name, table_name=table_name)
        op.create_index(index_name, table_name, ["idempotency_key"], unique=True)


def upgrade() -> None:
    for table_name in LEGACY_TIMESTAMP_TABLES:
        _set_created_at_not_null(table_name)
    _set_refresh_token_organization_not_null()
    _replace_idempotency_indexes()


def downgrade() -> None:
    for table_name in ("run_correlations", "delivery_outbox"):
        index_name = f"ix_{table_name}_idempotency_key"
        op.drop_index(index_name, table_name=table_name)
        op.create_index(index_name, table_name, ["idempotency_key"])

    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("refresh_tokens", recreate="always") as batch:
            batch.alter_column(
                "organization_id",
                existing_type=sa.Integer(),
                nullable=True,
            )
    else:
        op.alter_column(
            "refresh_tokens",
            "organization_id",
            existing_type=sa.Integer(),
            nullable=True,
        )
    for table_name in reversed(LEGACY_TIMESTAMP_TABLES):
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table(table_name, recreate="always") as batch:
                batch.alter_column(
                    "created_at",
                    existing_type=sa.DateTime(timezone=True),
                    nullable=True,
                )
        else:
            op.alter_column(
                table_name,
                "created_at",
                existing_type=sa.DateTime(timezone=True),
                nullable=True,
            )
