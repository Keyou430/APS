"""Add the platform-owned Phase D memory ledger."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

try:
    from pgvector.sqlalchemy import Vector
except ImportError:  # SQLite migration validation does not need PostgreSQL vector support.
    Vector = None  # type: ignore[assignment,misc]


revision: str = "20260811_0013"
down_revision: str | None = "20260810_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _scope_user_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id", "user_id"],
        ["organization_memberships.organization_id", "organization_memberships.user_id"],
        ondelete="CASCADE",
        name=name,
    )


def _record_fk(name: str, *, ondelete: str = "CASCADE") -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id", "user_id", "memory_id"],
        [
            "memory_records.organization_id",
            "memory_records.user_id",
            "memory_records.memory_id",
        ],
        ondelete=ondelete,
        name=name,
    )


def _add_chat_columns_and_constraints(dialect: str) -> None:
    op.add_column(
        "chat_sessions",
        sa.Column(
            "memory_mode",
            sa.String(10),
            nullable=False,
            server_default="off",
        ),
    )
    op.add_column(
        "chat_sessions",
        sa.Column(
            "revision",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    if dialect == "sqlite":
        with op.batch_alter_table("chat_sessions", recreate="always") as batch:
            batch.create_check_constraint(
                "ck_chat_sessions_memory_mode",
                "memory_mode IN ('off', 'auto')",
            )
        with op.batch_alter_table("chat_turns", recreate="always") as batch:
            batch.create_unique_constraint(
                "uq_chat_turns_org_id",
                ["organization_id", "id"],
            )
    else:
        op.create_check_constraint(
            "ck_chat_sessions_memory_mode",
            "chat_sessions",
            "memory_mode IN ('off', 'auto')",
        )
        op.create_unique_constraint(
            "uq_chat_turns_org_id",
            "chat_turns",
            ["organization_id", "id"],
        )


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        if Vector is None:
            raise RuntimeError("pgvector is required for PostgreSQL memory migrations")
        op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    embedding_type = Vector(1024) if dialect == "postgresql" and Vector is not None else sa.JSON()

    _add_chat_columns_and_constraints(dialect)

    op.create_table(
        "memory_capture_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.String(32), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("chat_session_id", sa.Integer(), nullable=True),
        sa.Column("chat_turn_id", sa.Integer(), nullable=True),
        sa.Column("source_kind", sa.String(30), nullable=False, server_default="user_text"),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="captured"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        _scope_user_fk("fk_memory_capture_sources_org_user"),
        sa.ForeignKeyConstraint(
            ["organization_id", "chat_session_id"],
            ["chat_sessions.organization_id", "chat_sessions.id"],
            ondelete="CASCADE",
            name="fk_memory_capture_sources_org_session",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "chat_turn_id"],
            ["chat_turns.organization_id", "chat_turns.id"],
            ondelete="CASCADE",
            name="fk_memory_capture_sources_org_turn",
        ),
        sa.UniqueConstraint("source_id", name="uq_memory_capture_sources_source_id"),
        sa.UniqueConstraint(
            "organization_id",
            "user_id",
            "id",
            name="uq_memory_capture_sources_org_user_id",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "chat_turn_id",
            "content_sha256",
            name="uq_memory_capture_sources_org_turn_hash",
        ),
        sa.CheckConstraint(
            "status IN ('captured', 'queued', 'completed', 'failed', 'cancelled', 'purged')",
            name="ck_memory_capture_sources_status",
        ),
    )
    op.create_index(
        "ix_memory_capture_sources_source_id",
        "memory_capture_sources",
        ["source_id"],
        unique=True,
    )
    op.create_index(
        "ix_memory_capture_sources_org_user",
        "memory_capture_sources",
        ["organization_id", "user_id"],
    )
    op.create_index(
        "ix_memory_capture_sources_org_session",
        "memory_capture_sources",
        ["organization_id", "chat_session_id"],
    )
    op.create_index(
        "ix_memory_capture_sources_org_turn",
        "memory_capture_sources",
        ["organization_id", "chat_turn_id"],
    )

    op.create_table(
        "memory_records",
        sa.Column("memory_id", sa.String(32), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("type", sa.String(30), nullable=False, server_default="memory"),
        sa.Column("layer", sa.String(2), nullable=False, server_default="L1"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("origin", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("source_summary", sa.String(255), nullable=True),
        sa.Column("supersedes_memory_id", sa.String(32), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("provider", sa.String(100), nullable=True),
        sa.Column("provider_version", sa.String(50), nullable=True),
        sa.Column("candidate_key", sa.String(64), nullable=True),
        sa.Column("embedding", embedding_type, nullable=True),
        sa.Column("embedding_model", sa.String(100), nullable=True),
        sa.Column("embedding_version", sa.String(50), nullable=True),
        sa.Column("embedding_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "embedding_state",
            sa.String(20),
            nullable=False,
            server_default="not_configured",
        ),
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
        sa.ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["organization_memberships.organization_id", "organization_memberships.user_id"],
            ondelete="RESTRICT",
            name="fk_memory_records_org_user",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "user_id", "supersedes_memory_id"],
            [
                "memory_records.organization_id",
                "memory_records.user_id",
                "memory_records.memory_id",
            ],
            ondelete="RESTRICT",
            name="fk_memory_records_org_user_supersedes",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "user_id",
            "memory_id",
            name="uq_memory_records_org_user_id",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "user_id",
            "candidate_key",
            name="uq_memory_records_org_user_candidate_key",
        ),
        sa.CheckConstraint(
            "type IN ('memory', 'fact', 'preference', 'decision', 'context')",
            name="ck_memory_records_type",
        ),
        sa.CheckConstraint("layer IN ('L1', 'L2', 'L3')", name="ck_memory_records_layer"),
        sa.CheckConstraint(
            "status IN ('candidate', 'active', 'superseded')",
            name="ck_memory_records_status",
        ),
        sa.CheckConstraint(
            "origin IN ('manual', 'extracted', 'imported')",
            name="ck_memory_records_origin",
        ),
        sa.CheckConstraint("revision > 0", name="ck_memory_records_revision_positive"),
        sa.CheckConstraint(
            "embedding_state IN ('not_configured', 'pending', 'ready', 'failed')",
            name="ck_memory_records_embedding_state",
        ),
    )
    op.create_index(
        "ix_memory_records_active_owner_list",
        "memory_records",
        ["organization_id", "user_id", "updated_at", "memory_id"],
        postgresql_where=sa.text("status = 'active'"),
        sqlite_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ix_memory_records_org_user_supersedes",
        "memory_records",
        ["organization_id", "user_id", "supersedes_memory_id"],
    )
    if dialect == "postgresql":
        op.create_index(
            "ix_memory_records_active_fts",
            "memory_records",
            [sa.text("to_tsvector('simple', content)")],
            postgresql_using="gin",
            postgresql_where=sa.text("status = 'active'"),
        )
        op.create_index(
            "ix_memory_records_active_embedding_hnsw",
            "memory_records",
            ["embedding"],
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_where=sa.text("embedding IS NOT NULL AND status = 'active'"),
        )

    op.create_table(
        "memory_embedding_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("memory_id", sa.String(32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_by", sa.String(100), nullable=True),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(100), nullable=True),
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
        _record_fk("fk_memory_embedding_jobs_org_user_record"),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'completed', 'failed', 'cancelled')",
            name="ck_memory_embedding_jobs_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_memory_embedding_jobs_attempts"),
        sa.CheckConstraint("max_attempts > 0", name="ck_memory_embedding_jobs_max_attempts"),
    )
    op.create_index(
        "ix_memory_embedding_jobs_org_user_record",
        "memory_embedding_jobs",
        ["organization_id", "user_id", "memory_id"],
    )
    op.create_index(
        "ix_memory_embedding_jobs_claim",
        "memory_embedding_jobs",
        ["available_at", "created_at", "id"],
        postgresql_where=sa.text("status = 'queued'"),
        sqlite_where=sa.text("status = 'queued'"),
    )

    op.create_table(
        "memory_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("memory_id", sa.String(32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("type", sa.String(30), nullable=False),
        sa.Column("layer", sa.String(2), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("origin", sa.String(20), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("source_summary", sa.String(255), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("provider", sa.String(100), nullable=True),
        sa.Column("provider_version", sa.String(50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        _record_fk("fk_memory_versions_org_user_record"),
        sa.UniqueConstraint("memory_id", "revision", name="uq_memory_versions_record_revision"),
    )
    op.create_index(
        "ix_memory_versions_org_user_record",
        "memory_versions",
        ["organization_id", "user_id", "memory_id"],
    )

    op.create_table(
        "memory_source_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("memory_id", sa.String(32), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("source_label", sa.String(255), nullable=True),
        sa.Column("source_content_sha256", sa.String(64), nullable=True),
        sa.Column("source_tombstoned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        _record_fk("fk_memory_source_links_org_user_record"),
        sa.ForeignKeyConstraint(
            ["organization_id", "user_id", "source_id"],
            [
                "memory_capture_sources.organization_id",
                "memory_capture_sources.user_id",
                "memory_capture_sources.id",
            ],
            ondelete="CASCADE",
            name="fk_memory_source_links_org_user_source",
        ),
        sa.UniqueConstraint("memory_id", "source_id", name="uq_memory_source_links_record_source"),
    )
    op.create_index(
        "ix_memory_source_links_org_user_record",
        "memory_source_links",
        ["organization_id", "user_id", "memory_id"],
    )
    op.create_index(
        "ix_memory_source_links_org_user_source",
        "memory_source_links",
        ["organization_id", "user_id", "source_id"],
    )

    op.create_table(
        "memory_extraction_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("provider_version", sa.String(50), nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_by", sa.String(100), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(100), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["organization_id", "user_id", "source_id"],
            [
                "memory_capture_sources.organization_id",
                "memory_capture_sources.user_id",
                "memory_capture_sources.id",
            ],
            ondelete="CASCADE",
            name="fk_memory_extraction_jobs_org_user_source",
        ),
        sa.UniqueConstraint(
            "source_id",
            "provider",
            "provider_version",
            name="uq_memory_extraction_jobs_source_provider_version",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'completed', 'failed', 'cancelled')",
            name="ck_memory_extraction_jobs_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_memory_extraction_jobs_attempts"),
        sa.CheckConstraint("max_attempts > 0", name="ck_memory_extraction_jobs_max_attempts"),
    )
    op.create_index(
        "ix_memory_extraction_jobs_org_user_source",
        "memory_extraction_jobs",
        ["organization_id", "user_id", "source_id"],
    )
    op.create_index(
        "ix_memory_extraction_jobs_claim",
        "memory_extraction_jobs",
        ["available_at", "created_at", "id"],
        postgresql_where=sa.text("status = 'queued'"),
        sqlite_where=sa.text("status = 'queued'"),
    )

    op.create_table(
        "memory_retrieval_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("chat_session_id", sa.Integer(), nullable=True),
        sa.Column("query_hmac", sa.String(64), nullable=True),
        sa.Column("query_hmac_version", sa.Integer(), nullable=True),
        sa.Column("memory_mode", sa.String(10), nullable=False, server_default="off"),
        sa.Column("retrieval_mode", sa.String(30), nullable=False, server_default="fts"),
        sa.Column("result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("outcome", sa.String(30), nullable=False, server_default="success"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        _scope_user_fk("fk_memory_retrieval_events_org_user"),
        sa.ForeignKeyConstraint(
            ["organization_id", "chat_session_id"],
            ["chat_sessions.organization_id", "chat_sessions.id"],
            name="fk_memory_retrieval_events_org_session",
        ),
    )
    op.create_index(
        "ix_memory_retrieval_events_org_user_created",
        "memory_retrieval_events",
        ["organization_id", "user_id", "created_at"],
    )
    op.create_index(
        "ix_memory_retrieval_events_org_session",
        "memory_retrieval_events",
        ["organization_id", "chat_session_id"],
    )


def _drop_chat_columns_and_constraints(dialect: str) -> None:
    if dialect == "sqlite":
        with op.batch_alter_table("chat_turns", recreate="always") as batch:
            batch.drop_constraint("uq_chat_turns_org_id", type_="unique")
        with op.batch_alter_table("chat_sessions", recreate="always") as batch:
            batch.drop_constraint("ck_chat_sessions_memory_mode", type_="check")
            batch.drop_column("memory_mode")
            batch.drop_column("revision")
    else:
        op.drop_constraint("uq_chat_turns_org_id", "chat_turns", type_="unique")
        op.drop_constraint("ck_chat_sessions_memory_mode", "chat_sessions", type_="check")
        op.drop_column("chat_sessions", "memory_mode")
        op.drop_column("chat_sessions", "revision")


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    op.drop_table("memory_retrieval_events")
    op.drop_table("memory_extraction_jobs")
    op.drop_table("memory_source_links")
    op.drop_table("memory_versions")
    op.drop_table("memory_embedding_jobs")
    op.drop_table("memory_records")
    op.drop_table("memory_capture_sources")
    _drop_chat_columns_and_constraints(dialect)
