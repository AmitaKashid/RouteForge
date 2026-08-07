"""SQLAlchemy persistence models for RouteForge control plane state."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for SQLAlchemy declarative models."""

    pass


class TeamModel(Base):
    """Team tenant identity model."""

    __tablename__ = "teams"

    team_id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    api_keys: Mapped[list["ApiKeyModel"]] = relationship("ApiKeyModel", back_populates="team")
    inference_records: Mapped[list["InferenceRecordModel"]] = relationship(
        "InferenceRecordModel", back_populates="team"
    )
    limits: Mapped["TeamLimitsModel | None"] = relationship(
        "TeamLimitsModel", back_populates="team", uselist=False
    )


class TeamLimitsModel(Base):
    """Per-team operational rate limits and monthly USD budget configuration."""

    __tablename__ = "team_limits"

    team_id: Mapped[str] = mapped_column(
        String, ForeignKey("teams.team_id", ondelete="CASCADE"), primary_key=True
    )
    requests_per_minute: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_per_minute: Mapped[int] = mapped_column(Integer, nullable=False)
    monthly_budget_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    team: Mapped[TeamModel] = relationship("TeamModel", back_populates="limits")

    __table_args__ = (
        CheckConstraint("requests_per_minute > 0", name="ck_team_limits_requests_positive"),
        CheckConstraint("tokens_per_minute > 0", name="ck_team_limits_tokens_positive"),
        CheckConstraint("monthly_budget_usd >= 0", name="ck_team_limits_budget_non_negative"),
    )


class ApiKeyModel(Base):
    """API key record for team authentication."""

    __tablename__ = "api_keys"

    key_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    team_id: Mapped[str] = mapped_column(
        String, ForeignKey("teams.team_id"), nullable=False, index=True
    )
    key_prefix: Mapped[str] = mapped_column(String, nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    team: Mapped[TeamModel] = relationship("TeamModel", back_populates="api_keys")


class InferenceRecordModel(Base):
    """Durable record of an inference request, routing decision, and usage metrics."""

    __tablename__ = "inference_records"

    request_id: Mapped[str] = mapped_column(String, primary_key=True)
    team_id: Mapped[str] = mapped_column(
        String, ForeignKey("teams.team_id"), nullable=False, index=True
    )
    feature_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    policy_id: Mapped[str] = mapped_column(String, nullable=False)
    policy_version: Mapped[str] = mapped_column(String, nullable=False)
    selected_model_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    selected_provider_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    routing_reason: Mapped[str] = mapped_column(String, nullable=False)
    candidate_decisions: Mapped[Any] = mapped_column(
        JSONB, nullable=False
    )  # JSONB array/dictionary
    status: Mapped[str] = mapped_column(
        String, nullable=False, index=True
    )  # SUCCEEDED, NO_ELIGIBLE_MODEL, PROVIDER_ERROR, BUDGET_RESERVED, BUDGET_REJECTED
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt_hash: Mapped[str] = mapped_column(String, nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    reserved_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    accounted_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    cost_source: Mapped[str | None] = mapped_column(String, nullable=True)
    budget_period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    provider_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    execution_attempts: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default="[]")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    initial_model_id: Mapped[str | None] = mapped_column(String, nullable=True)
    initial_provider_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    team: Mapped[TeamModel] = relationship("TeamModel", back_populates="inference_records")

    __table_args__ = (
        Index("idx_inference_records_team_created", "team_id", "created_at"),
        Index(
            "idx_inference_records_budget_lookup",
            "team_id",
            "budget_period_start",
            "status",
        ),
    )


class QualityVerificationRecord(Base):
    """Durable record of an asynchronous quality verification job and comparison result."""

    __tablename__ = "quality_verifications"

    verification_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    request_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("inference_records.request_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    team_id: Mapped[str] = mapped_column(
        String, ForeignKey("teams.team_id", ondelete="CASCADE"), nullable=False, index=True
    )
    feature_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    policy_id: Mapped[str] = mapped_column(String, nullable=False)
    policy_version: Mapped[str] = mapped_column(String, nullable=False)

    selected_model_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    selected_provider_id: Mapped[str] = mapped_column(String, nullable=False)
    reference_model_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    reference_provider_id: Mapped[str] = mapped_column(String, nullable=False)

    strategy: Mapped[str] = mapped_column(String, nullable=False)
    minimum_score: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)

    status: Mapped[str] = mapped_column(
        String, nullable=False, index=True
    )  # QUEUED, RUNNING, SUCCEEDED, FAILED, SKIPPED
    score: Mapped[Decimal | None] = mapped_column(Numeric(6, 5), nullable=True)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True, index=True)
    failure_code: Mapped[str | None] = mapped_column(String, nullable=True)

    selected_output_hash: Mapped[str] = mapped_column(String, nullable=False)
    reference_output_hash: Mapped[str | None] = mapped_column(String, nullable=True)

    reference_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reference_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reference_total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reference_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reference_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    reference_cost_source: Mapped[str | None] = mapped_column(String, nullable=True)

    delivery_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    team: Mapped[TeamModel] = relationship("TeamModel")
    inference_record: Mapped[InferenceRecordModel] = relationship("InferenceRecordModel")

    __table_args__ = (
        Index("idx_quality_verifications_team_queued", "team_id", "queued_at"),
        Index("idx_quality_verifications_feature_queued", "feature_id", "queued_at"),
        CheckConstraint(
            "reference_input_tokens IS NULL OR reference_input_tokens >= 0",
            name="ck_quality_verifications_ref_input_tokens_non_negative",
        ),
        CheckConstraint(
            "reference_output_tokens IS NULL OR reference_output_tokens >= 0",
            name="ck_quality_verifications_ref_output_tokens_non_negative",
        ),
        CheckConstraint(
            "reference_total_tokens IS NULL OR reference_total_tokens >= 0",
            name="ck_quality_verifications_ref_total_tokens_non_negative",
        ),
        CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 1)",
            name="ck_quality_verifications_score_range",
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= queued_at",
            name="ck_quality_verifications_completed_after_queued",
        ),
    )
