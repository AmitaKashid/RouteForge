"""Initial database schema for teams, API keys, and inference records.

Revision ID: 001_initial_schema
Revises: None
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. teams table
    op.create_table(
        "teams",
        sa.Column("team_id", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("team_id"),
    )

    # 2. api_keys table
    op.create_table(
        "api_keys",
        sa.Column("key_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("team_id", sa.String(), nullable=False),
        sa.Column("key_prefix", sa.String(), nullable=False),
        sa.Column("key_hash", sa.String(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["team_id"], ["teams.team_id"]),
        sa.PrimaryKeyConstraint("key_id"),
        sa.UniqueConstraint("key_hash"),
    )
    op.create_index("ix_api_keys_key_prefix", "api_keys", ["key_prefix"], unique=False)
    op.create_index("ix_api_keys_team_id", "api_keys", ["team_id"], unique=False)

    # 3. inference_records table
    op.create_table(
        "inference_records",
        sa.Column("request_id", sa.String(), nullable=False),
        sa.Column("team_id", sa.String(), nullable=False),
        sa.Column("feature_id", sa.String(), nullable=False),
        sa.Column("policy_id", sa.String(), nullable=False),
        sa.Column("policy_version", sa.String(), nullable=False),
        sa.Column("selected_model_id", sa.String(), nullable=True),
        sa.Column("selected_provider_id", sa.String(), nullable=True),
        sa.Column("routing_reason", sa.String(), nullable=False),
        sa.Column("candidate_decisions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("prompt_hash", sa.String(), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("accounted_cost_usd", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("cost_source", sa.String(), nullable=True),
        sa.Column("provider_latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["teams.team_id"]),
        sa.PrimaryKeyConstraint("request_id"),
    )
    op.create_index(
        "idx_inference_records_team_created",
        "inference_records",
        ["team_id", "created_at"],
        unique=False,
    )
    op.create_index("ix_inference_records_team_id", "inference_records", ["team_id"], unique=False)
    op.create_index(
        "ix_inference_records_selected_model_id",
        "inference_records",
        ["selected_model_id"],
        unique=False,
    )
    op.create_index(
        "ix_inference_records_selected_provider_id",
        "inference_records",
        ["selected_provider_id"],
        unique=False,
    )
    op.create_index(
        "ix_inference_records_feature_id", "inference_records", ["feature_id"], unique=False
    )
    op.create_index("ix_inference_records_status", "inference_records", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_inference_records_status", table_name="inference_records")
    op.drop_index("ix_inference_records_feature_id", table_name="inference_records")
    op.drop_index("ix_inference_records_selected_provider_id", table_name="inference_records")
    op.drop_index("ix_inference_records_selected_model_id", table_name="inference_records")
    op.drop_index("ix_inference_records_team_id", table_name="inference_records")
    op.drop_index("idx_inference_records_team_created", table_name="inference_records")
    op.drop_table("inference_records")

    op.drop_index("ix_api_keys_team_id", table_name="api_keys")
    op.drop_index("ix_api_keys_key_prefix", table_name="api_keys")
    op.drop_table("api_keys")

    op.drop_table("teams")
