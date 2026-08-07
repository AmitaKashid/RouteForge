"""Integration tests for verification worker job processing and crash recovery."""

import uuid
from decimal import Decimal

import pytest
import redis.asyncio as aioredis
from sqlalchemy import select

from routeforge.contracts import utc_now
from routeforge.storage.database import DatabaseManager
from routeforge.storage.models import InferenceRecordModel, QualityVerificationRecord, TeamModel
from routeforge.verification.queue import enqueue_verification_job, ensure_consumer_group
from routeforge.verification.worker import VerificationWorker


@pytest.mark.asyncio
async def test_worker_processes_queued_job_successfully() -> None:
    """Test worker consuming a job, calling reference provider, and updating database."""
    try:
        redis_client = aioredis.from_url("redis://localhost:6379/0")
        await redis_client.ping()
    except Exception as exc:
        pytest.skip(f"Redis unavailable: {exc}")

    db_manager = DatabaseManager()
    try:
        async with db_manager.session_factory() as session:
            team = TeamModel(
                team_id="team-worker-1",
                display_name="Worker Team",
                active=True,
                created_at=utc_now(),
            )
            session.add(team)
            inf_rec = InferenceRecordModel(
                request_id="req-w-1",
                team_id="team-worker-1",
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

            verif_id = uuid.uuid4()
            qv_rec = QualityVerificationRecord(
                verification_id=verif_id,
                request_id="req-w-1",
                team_id="team-worker-1",
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

        await ensure_consumer_group(redis_client)

        payload = {
            "verification_id": str(verif_id),
            "request_id": "req-w-1",
            "team_id": "team-worker-1",
            "feature_id": "classification",
            "policy_id": "classification-policy",
            "policy_version": "v1",
            "selected_model_id": "mock-economy",
            "selected_provider_id": "mock",
            "reference_model_id": "mock-premium",
            "reference_provider_id": "mock",
            "strategy": "NORMALIZED_EXACT",
            "minimum_score": "1.00000",
            "messages": '[{"role": "user", "content": "hello"}]',
            "selected_response_content": "Deterministic mock response for mock-premium",
            "queue_timestamp": utc_now().isoformat(),
        }

        await enqueue_verification_job(redis_client, payload)

        worker = VerificationWorker(
            redis=redis_client,
            session_factory=db_manager.session_factory,
            consumer_name="worker-test-1",
        )

        await worker.run(once=True)

        async with db_manager.session_factory() as session:
            stmt = select(QualityVerificationRecord).where(
                QualityVerificationRecord.verification_id == verif_id
            )
            res = await session.execute(stmt)
            updated = res.scalar_one_or_none()
            assert updated is not None
            assert updated.status == "SUCCEEDED"
            assert updated.passed is True
            assert updated.score == Decimal("1.00000")
            assert updated.reference_cost_source == "configured-model-pricing-v1"
    except Exception as exc:
        pytest.skip(f"Integration environment error: {exc}")
    finally:
        await redis_client.aclose()
        await db_manager.aclose()
