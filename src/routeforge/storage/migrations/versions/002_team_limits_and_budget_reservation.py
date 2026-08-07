"""Team limits and budget reservation columns.

Revision ID: 002_team_limits_and_budget_reservation
Revises: 001_initial_schema
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "002_team_limits_and_budget_reservation"
down_revision: str | None = "001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. team_limits table
    op.create_table(
        "team_limits",
        sa.Column("team_id", sa.String(), nullable=False),
        sa.Column("requests_per_minute", sa.Integer(), nullable=False),
        sa.Column("tokens_per_minute", sa.Integer(), nullable=False),
        sa.Column("monthly_budget_usd", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("requests_per_minute > 0", name="ck_team_limits_requests_positive"),
        sa.CheckConstraint("tokens_per_minute > 0", name="ck_team_limits_tokens_positive"),
        sa.CheckConstraint("monthly_budget_usd >= 0", name="ck_team_limits_budget_non_negative"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.team_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("team_id"),
    )

    # 2. Add columns to inference_records table
    op.add_column(
        "inference_records",
        sa.Column("estimated_cost_usd", sa.Numeric(precision=18, scale=8), nullable=True),
    )
    op.add_column(
        "inference_records",
        sa.Column("reserved_cost_usd", sa.Numeric(precision=18, scale=8), nullable=True),
    )
    op.add_column(
        "inference_records",
        sa.Column("budget_period_start", sa.Date(), nullable=True),
    )

    # 3. Create index for budget lookup
    op.create_index(
        "idx_inference_records_budget_lookup",
        "inference_records",
        ["team_id", "budget_period_start", "status"],
    )


def downgrade() -> None:
    op.drop_index("idx_inference_records_budget_lookup", table_name="inference_records")
    op.drop_column("inference_records", "budget_period_start")
    op.drop_column("inference_records", "reserved_cost_usd")
    op.drop_column("inference_records", "estimated_cost_usd")
    op.drop_table("team_limits")
