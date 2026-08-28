"""Persist native Hermes cron ownership on pipeline tasks."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260828_0025"
down_revision: str | None = "20260827_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("pipeline_tasks", sa.Column("hermes_cron_job_id", sa.String(120), nullable=True))
    op.create_index("ix_pipeline_tasks_hermes_cron_job_id", "pipeline_tasks", ["hermes_cron_job_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_pipeline_tasks_hermes_cron_job_id", table_name="pipeline_tasks")
    op.drop_column("pipeline_tasks", "hermes_cron_job_id")
