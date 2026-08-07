"""Create quality_verifications table for asynchronous quality verification metadata.

Revision ID: 004_quality_verifications
Revises: 003_execution_attempts_and_resilience
Create Date: 2026-08-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "004_quality_verifications"
down_revision: str | None = "003_execution_attempts_and_resilience"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "quality_verifications",
        sa.Column("verification_id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "request_id",
            sa.String(),
            sa.ForeignKey("inference_records.request_id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "team_id",
            sa.String(),
            sa.ForeignKey("teams.team_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("feature_id", sa.String(), nullable=False),
        sa.Column("policy_id", sa.String(), nullable=False),
        sa.Column("policy_version", sa.String(), nullable=False),
        sa.Column("selected_model_id", sa.String(), nullable=False),
        sa.Column("selected_provider_id", sa.String(), nullable=False),
        sa.Column("reference_model_id", sa.String(), nullable=False),
        sa.Column("reference_provider_id", sa.String(), nullable=False),
        sa.Column("strategy", sa.String(), nullable=False),
        sa.Column("minimum_score", sa.Numeric(6, 5), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("score", sa.Numeric(6, 5), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("failure_code", sa.String(), nullable=True),
        sa.Column("selected_output_hash", sa.String(), nullable=False),
        sa.Column("reference_output_hash", sa.String(), nullable=True),
        sa.Column("reference_input_tokens", sa.Integer(), nullable=True),
        sa.Column("reference_output_tokens", sa.Integer(), nullable=True),
        sa.Column("reference_total_tokens", sa.Integer(), nullable=True),
        sa.Column("reference_latency_ms", sa.Integer(), nullable=True),
        sa.Column("reference_cost_usd", sa.Numeric(18, 8), nullable=True),
        sa.Column("reference_cost_source", sa.String(), nullable=True),
        sa.Column("delivery_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "reference_input_tokens IS NULL OR reference_input_tokens >= 0",
            name="ck_quality_verifications_ref_input_tokens_non_negative",
        ),
        sa.CheckConstraint(
            "reference_output_tokens IS NULL OR reference_output_tokens >= 0",
            name="ck_quality_verifications_ref_output_tokens_non_negative",
        ),
        sa.CheckConstraint(
            "reference_total_tokens IS NULL OR reference_total_tokens >= 0",
            name="ck_quality_verifications_ref_total_tokens_non_negative",
        ),
        sa.CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 1)",
            name="ck_quality_verifications_score_range",
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= queued_at",
            name="ck_quality_verifications_completed_after_queued",
        ),
    )

    op.create_index(
        "idx_quality_verifications_team_queued",
        "quality_verifications",
        ["team_id", "queued_at"],
    )
    op.create_index(
        "idx_quality_verifications_feature_queued",
        "quality_verifications",
        ["feature_id", "queued_at"],
    )
    op.create_index("idx_quality_verifications_status", "quality_verifications", ["status"])
    op.create_index(
        "idx_quality_verifications_selected_model",
        "quality_verifications",
        ["selected_model_id"],
    )
    op.create_index(
        "idx_quality_verifications_reference_model",
        "quality_verifications",
        ["reference_model_id"],
    )
    op.create_index("idx_quality_verifications_passed", "quality_verifications", ["passed"])


def downgrade() -> None:
    op.drop_index("idx_quality_verifications_passed", table_name="quality_verifications")
    op.drop_index("idx_quality_verifications_reference_model", table_name="quality_verifications")
    op.drop_index("idx_quality_verifications_selected_model", table_name="quality_verifications")
    op.drop_index("idx_quality_verifications_status", table_name="quality_verifications")
    op.drop_index("idx_quality_verifications_feature_queued", table_name="quality_verifications")
    op.drop_index("idx_quality_verifications_team_queued", table_name="quality_verifications")
    op.drop_table("quality_verifications")
