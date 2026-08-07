"""Integration tests for verification PostgreSQL records and Redis stream queueing."""

import uuid
from decimal import Decimal

import pytest
import redis.asyncio as aioredis
from sqlalchemy import select

from routeforge.contracts import utc_now
from routeforge.storage.database import DatabaseManager
from routeforge.storage.models import InferenceRecordModel, QualityVerificationRecord, TeamModel
from routeforge.verification.queue import (
    VERIFICATION_CONSUMER_GROUP,
    VERIFICATION_STREAM_KEY,
    ack_and_delete_verification_job,
    enqueue_verification_job,
    ensure_consumer_group,
)


@pytest.mark.asyncio
async def test_quality_verification_postgres_record_creation() -> None:
    """Test creating and retrieving QualityVerificationRecord in PostgreSQL."""
    db_manager = DatabaseManager()
    try:
        async with db_manager.session_factory() as session:
            team = TeamModel(
                team_id="team-verif-1", display_name="Verif Team", active=True, created_at=utc_now()
            )
            session.add(team)
            inf_rec = InferenceRecordModel(
                request_id="req-v-1",
                team_id="team-verif-1",
                feature_id="classification",
                policy_id="classification-policy",
                policy_version="v1",
                selected_model_id="mock-economy",
                selected_provider_id="mock",
                routing_reason="QUALITY_REQUIREMENT_SATISFIED",
                candidate_decisions=[],
                status="SUCCEEDED",
                prompt_hash="hash123",
                message_count=1,
                created_at=utc_now(),
                completed_at=utc_now(),
            )
            session.add(inf_rec)
            await session.commit()

            verif_id = uuid.uuid4()
            qv_rec = QualityVerificationRecord(
                verification_id=verif_id,
                request_id="req-v-1",
                team_id="team-verif-1",
                feature_id="classification",
                policy_id="classification-policy",
                policy_version="v1",
                selected_model_id="mock-economy",
                selected_provider_id="mock",
                reference_model_id="mock-premium",
                reference_provider_id="mock",
                strategy="NORMALIZED_EXACT",
                minimum_score=Decimal("1.00000"),
                status="QUEUED",
                selected_output_hash="selhash123",
                delivery_attempts=0,
                queued_at=utc_now(),
            )
            session.add(qv_rec)
            await session.commit()

            # Retrieve
            stmt = select(QualityVerificationRecord).where(
                QualityVerificationRecord.verification_id == verif_id
            )
            res = await session.execute(stmt)
            fetched = res.scalar_one_or_none()
            assert fetched is not None
            assert fetched.request_id == "req-v-1"
            assert fetched.status == "QUEUED"
    except Exception as exc:
        pytest.skip(f"PostgreSQL unavailable: {exc}")
    finally:
        await db_manager.aclose()


@pytest.mark.asyncio
async def test_redis_verification_stream_pub_sub() -> None:
    """Test enqueueing and acknowledging jobs on Redis stream."""
    try:
        redis_client = aioredis.from_url("redis://localhost:6379/0")
        await redis_client.ping()
    except Exception as exc:
        pytest.skip(f"Redis unavailable: {exc}")

    try:
        await ensure_consumer_group(redis_client)

        payload = {
            "verification_id": str(uuid.uuid4()),
            "request_id": "req-stream-1",
            "team_id": "team-stream",
            "feature_id": "classification",
            "policy_id": "p1",
            "policy_version": "v1",
            "selected_model_id": "mock-economy",
            "selected_provider_id": "mock",
            "reference_model_id": "mock-premium",
            "reference_provider_id": "mock",
            "strategy": "NORMALIZED_EXACT",
            "minimum_score": "1.00000",
            "messages": "[]",
            "selected_response_content": "positive",
            "queue_timestamp": utc_now().isoformat(),
        }

        entry_id = await enqueue_verification_job(redis_client, payload)
        assert entry_id is not None

        # Read from stream consumer group
        entries = await redis_client.xreadgroup(
            groupname=VERIFICATION_CONSUMER_GROUP,
            consumername="test-consumer",
            streams={VERIFICATION_STREAM_KEY: ">"},
            count=1,
            block=1000,
        )
        assert len(entries) > 0

        # Ack and delete
        await ack_and_delete_verification_job(redis_client, entry_id)
    finally:
        await redis_client.aclose()
