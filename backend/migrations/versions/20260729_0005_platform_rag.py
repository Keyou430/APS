"""Add platform-owned RAG persistence and chat backend routing."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

try:
    from pgvector.sqlalchemy import Vector
except ImportError:  # SQLite-only migration checks do not need the PostgreSQL type package.
    Vector = None  # type: ignore[assignment,misc]


revision: str = "20260729_0005"
down_revision: str | None = "20260727_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        if Vector is None:
            raise RuntimeError("pgvector is required for PostgreSQL RAG migrations")
        op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    embedding_type = Vector(1024) if dialect == "postgresql" and Vector is not None else sa.JSON()

    op.create_table(
        "knowledge_ingestion_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("knowledge_entry_id", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("parser_version", sa.String(50), nullable=False),
        sa.Column("embedding_model", sa.String(100), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False, server_default="1024"),
        sa.Column("last_error_code", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_entry_id"],
            ["knowledge_entries.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "knowledge_entry_id",
            "content_sha256",
            name="uq_knowledge_ingestion_jobs_entry_hash",
        ),
    )
    op.create_index(
        "ix_knowledge_ingestion_jobs_scope",
        "knowledge_ingestion_jobs",
        ["organization_id", "user_id", "knowledge_entry_id"],
    )
    op.create_index(
        "ix_knowledge_ingestion_jobs_status_created_at",
        "knowledge_ingestion_jobs",
        ["status", "created_at"],
    )

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("knowledge_entry_id", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_sha256", sa.String(64), nullable=False),
        sa.Column("source_locator", sa.String(500), nullable=True),
        sa.Column("embedding", embedding_type, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_entry_id"],
            ["knowledge_entries.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "knowledge_entry_id",
            "content_sha256",
            "ordinal",
            name="uq_knowledge_chunks_entry_hash_ordinal",
        ),
    )
    op.create_index(
        "ix_knowledge_chunks_scope",
        "knowledge_chunks",
        ["organization_id", "user_id", "knowledge_entry_id"],
    )
    if dialect == "postgresql":
        op.create_index(
            "ix_knowledge_chunks_text_fts",
            "knowledge_chunks",
            [sa.text("to_tsvector('simple', text)")],
            postgresql_using="gin",
        )
        op.create_index(
            "ix_knowledge_chunks_embedding_hnsw",
            "knowledge_chunks",
            ["embedding"],
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        )

    op.create_table(
        "knowledge_retrieval_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("chat_session_id", sa.Integer(), nullable=False),
        sa.Column("query_sha256", sa.String(64), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(30), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_knowledge_retrieval_events_scope",
        "knowledge_retrieval_events",
        ["organization_id", "user_id", "chat_session_id"],
    )
    op.create_index(
        "ix_knowledge_retrieval_events_session_created_at",
        "knowledge_retrieval_events",
        ["chat_session_id", "created_at"],
    )

    op.add_column(
        "chat_sessions",
        sa.Column("hermes_backend", sa.String(20), nullable=True),
    )
    op.execute(
        sa.text("UPDATE chat_sessions SET hermes_backend = 'agent' WHERE hermes_backend IS NULL")
    )
    if dialect == "sqlite":
        with op.batch_alter_table("chat_sessions", recreate="always") as batch:
            batch.alter_column(
                "hermes_backend",
                existing_type=sa.String(20),
                nullable=False,
            )
    else:
        op.alter_column(
            "chat_sessions",
            "hermes_backend",
            existing_type=sa.String(20),
            nullable=False,
        )


def downgrade() -> None:
    op.drop_column("chat_sessions", "hermes_backend")
    op.drop_table("knowledge_retrieval_events")
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_ingestion_jobs")
