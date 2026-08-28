"""Store feedback-specific prompts for regenerated pipeline runs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260827_0024"
down_revision: str | None = "20260827_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pipeline_runs",
        sa.Column("prompt_override", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pipeline_runs", "prompt_override")
