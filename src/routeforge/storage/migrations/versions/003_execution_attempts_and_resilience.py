"""Execution attempts, retry count, fallback used, and initial selection columns.

Revision ID: 003_execution_attempts_and_resilience
Revises: 002_team_limits_and_budget_reservation
Create Date: 2026-08-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "003_execution_attempts_and_resilience"
down_revision: str | None = "002_team_limits_and_budget_reservation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "inference_records",
        sa.Column("execution_attempts", JSONB(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "inference_records",
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "inference_records",
        sa.Column("fallback_used", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "inference_records",
        sa.Column("initial_model_id", sa.String(), nullable=True),
    )
    op.add_column(
        "inference_records",
        sa.Column("initial_provider_id", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("inference_records", "initial_provider_id")
    op.drop_column("inference_records", "initial_model_id")
    op.drop_column("inference_records", "fallback_used")
    op.drop_column("inference_records", "retry_count")
    op.drop_column("inference_records", "execution_attempts")
