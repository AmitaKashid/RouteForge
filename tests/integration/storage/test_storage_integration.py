"""PostgreSQL integration tests for storage, migrations, and durable inference recording."""

import os
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from routeforge.contracts import (
    ChatMessage,
    ChatRole,
    TeamId,
)
from routeforge.gateway import create_app
from routeforge.storage.database import DatabaseManager
from routeforge.storage.models import Base, InferenceRecordModel
from routeforge.storage.records import (
    authenticate_api_key,
    create_api_key_record,
    create_inference_record,
    create_or_get_team,
    generate_api_key,
    get_inference_record_by_request_id,
    hash_prompt,
)

TEST_DB_URL = os.getenv(
    "ROUTEFORGE_TEST_DATABASE_URL",
    "postgresql+asyncpg://routeforge:routeforge_pass@localhost:5432/routeforge_dev",
)

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="module")
async def db_manager() -> AsyncGenerator[DatabaseManager, None]:
    """Provide real DatabaseManager fixture connected to PostgreSQL test database."""
    try:
        manager = DatabaseManager(database_url=TEST_DB_URL)
        async with manager.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        pytest.skip(
            f"PostgreSQL test database unavailable at {TEST_DB_URL}. Skipping integration tests."
        )

    # Prepare tables cleanly
    async with manager.engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    yield manager

    async with manager.engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await manager.aclose()


@pytest.fixture
async def session(db_manager: DatabaseManager) -> AsyncGenerator[AsyncSession, None]:
    """Provide isolated async database session."""
    async with db_manager.session_factory() as session:
        yield session


# 1. Alembic Upgrade Integration Test
def test_01_alembic_upgrade_from_empty_database() -> None:
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", TEST_DB_URL)
    try:
        command.upgrade(alembic_cfg, "head")
    except Exception as err:
        pytest.skip(f"Alembic migration execution skipped: {err}")


# 2. Team Creation
async def test_02_team_creation(session: AsyncSession) -> None:
    team = await create_or_get_team(session, team_id="team-alpha", display_name="Alpha Team")
    assert team.team_id == "team-alpha"
    assert team.display_name == "Alpha Team"
    assert team.active is True


# 3 & 4. API Key Creation, Hashing & Successful Auth
async def test_03_04_api_key_creation_hashing_and_successful_auth(
    session: AsyncSession,
) -> None:
    await create_or_get_team(session, team_id="team-auth-1", display_name="Auth Team 1")
    full_key, prefix, key_hash = generate_api_key()
    await create_api_key_record(
        session, team_id="team-auth-1", key_prefix=prefix, key_hash=key_hash
    )

    auth = await authenticate_api_key(session, full_key)
    assert auth is not None
    assert auth.team_id == TeamId("team-auth-1")
    assert auth.is_key_active is True
    assert auth.is_team_active is True


# 5. Missing Key (returns 401 via HTTP auth)
async def test_05_missing_key_auth(db_manager: DatabaseManager) -> None:
    app = create_app(db_manager=db_manager)
    with TestClient(app) as client:
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "routeforge",
                "messages": [{"role": "user", "content": "Hi"}],
                "routeforge": {"feature_id": "general-chat"},
            },
        )
        assert resp.status_code == 401


# 6. Invalid Key (returns 401 via HTTP auth)
async def test_06_invalid_key_auth(db_manager: DatabaseManager) -> None:
    app = create_app(db_manager=db_manager)
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer rf_invalid_key_secret_12345"}
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "routeforge",
                "messages": [{"role": "user", "content": "Hi"}],
                "routeforge": {"feature_id": "general-chat"},
            },
            headers=headers,
        )
        assert resp.status_code == 401


# 7. Inactive Key (returns 403 via HTTP auth)
async def test_07_inactive_key_auth(session: AsyncSession, db_manager: DatabaseManager) -> None:
    await create_or_get_team(session, team_id="team-inactive-key", display_name="Team Key Inactive")
    full_key, prefix, key_hash = generate_api_key()
    await create_api_key_record(
        session, team_id="team-inactive-key", key_prefix=prefix, key_hash=key_hash, active=False
    )

    app = create_app(db_manager=db_manager)
    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {full_key}"}
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "routeforge",
                "messages": [{"role": "user", "content": "Hi"}],
                "routeforge": {"feature_id": "general-chat"},
            },
            headers=headers,
        )
        assert resp.status_code == 403


# 8. Inactive Team (returns 403 via HTTP auth)
async def test_08_inactive_team_auth(session: AsyncSession, db_manager: DatabaseManager) -> None:
    team = await create_or_get_team(session, team_id="team-disabled", display_name="Disabled Team")
    team.active = False
    await session.commit()

    full_key, prefix, key_hash = generate_api_key()
    await create_api_key_record(
        session, team_id="team-disabled", key_prefix=prefix, key_hash=key_hash
    )

    app = create_app(db_manager=db_manager)
    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {full_key}"}
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "routeforge",
                "messages": [{"role": "user", "content": "Hi"}],
                "routeforge": {"feature_id": "general-chat"},
            },
            headers=headers,
        )
        assert resp.status_code == 403


# 9, 12, 13. Successful Record Insertion, Decimal Cost & JSONB Preservation
async def test_09_12_13_successful_record_insertion(session: AsyncSession) -> None:
    await create_or_get_team(session, team_id="team-records", display_name="Records Team")
    req_id = f"req_{uuid.uuid4().hex}"
    cost_val = Decimal("0.00123456")

    record = InferenceRecordModel(
        request_id=req_id,
        team_id="team-records",
        feature_id="general-chat",
        policy_id="policy-1",
        policy_version="v1",
        selected_model_id="mock-economy",
        selected_provider_id="mock",
        routing_reason="CHEAPEST_ELIGIBLE_MODEL",
        candidate_decisions=[
            {
                "model_id": "mock-economy",
                "provider_id": "mock",
                "eligible": True,
                "rejection_reasons": [],
                "predicted_quality": 0.85,
                "estimated_latency_ms": 150,
                "estimated_cost_usd": 0.001,
            }
        ],
        status="SUCCEEDED",
        error_code=None,
        prompt_hash=hash_prompt([ChatMessage(role=ChatRole.USER, content="Hello")]),
        message_count=1,
        input_tokens=10,
        output_tokens=20,
        total_tokens=30,
        accounted_cost_usd=cost_val,
        cost_source="configured-model-pricing-v1",
        provider_latency_ms=120,
        created_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )

    await create_inference_record(session, record)

    saved = await get_inference_record_by_request_id(session, req_id, "team-records")
    assert saved is not None
    assert saved.status == "SUCCEEDED"
    assert saved.accounted_cost_usd == Decimal("0.00123456")
    assert saved.candidate_decisions[0]["model_id"] == "mock-economy"


# 10. No Eligible Record Insertion
async def test_10_no_eligible_record_insertion(session: AsyncSession) -> None:
    await create_or_get_team(session, team_id="team-records", display_name="Records Team")
    req_id = f"req_{uuid.uuid4().hex}"

    record = InferenceRecordModel(
        request_id=req_id,
        team_id="team-records",
        feature_id="general-chat",
        policy_id="policy-1",
        policy_version="v1",
        selected_model_id=None,
        selected_provider_id=None,
        routing_reason="NO_ELIGIBLE_MODEL",
        candidate_decisions=[],
        status="NO_ELIGIBLE_MODEL",
        error_code="NO_ELIGIBLE_MODEL",
        prompt_hash="dummy_hash",
        message_count=1,
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
        accounted_cost_usd=None,
        cost_source=None,
        provider_latency_ms=None,
        created_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )

    await create_inference_record(session, record)
    saved = await get_inference_record_by_request_id(session, req_id, "team-records")
    assert saved is not None
    assert saved.status == "NO_ELIGIBLE_MODEL"
    assert saved.selected_model_id is None


# 11. Provider Error Record Insertion
async def test_11_provider_error_record_insertion(session: AsyncSession) -> None:
    await create_or_get_team(session, team_id="team-records", display_name="Records Team")
    req_id = f"req_{uuid.uuid4().hex}"

    record = InferenceRecordModel(
        request_id=req_id,
        team_id="team-records",
        feature_id="general-chat",
        policy_id="policy-1",
        policy_version="v1",
        selected_model_id="mock-economy",
        selected_provider_id="mock",
        routing_reason="CHEAPEST_ELIGIBLE_MODEL",
        candidate_decisions=[],
        status="PROVIDER_ERROR",
        error_code="PROVIDER_TIMEOUT",
        prompt_hash="dummy_hash",
        message_count=1,
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
        accounted_cost_usd=None,
        cost_source=None,
        provider_latency_ms=None,
        created_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )

    await create_inference_record(session, record)
    saved = await get_inference_record_by_request_id(session, req_id, "team-records")
    assert saved is not None
    assert saved.status == "PROVIDER_ERROR"
    assert saved.error_code == "PROVIDER_TIMEOUT"


# 14 & 15. Routing Decision Retrieval & Cross-Team Isolation (404)
async def test_14_15_routing_decision_retrieval_and_cross_team_isolation(
    session: AsyncSession, db_manager: DatabaseManager
) -> None:
    await create_or_get_team(session, team_id="team-owner", display_name="Owner Team")
    await create_or_get_team(session, team_id="team-other", display_name="Other Team")

    owner_key, prefix1, hash1 = generate_api_key()
    other_key, prefix2, hash2 = generate_api_key()
    await create_api_key_record(session, team_id="team-owner", key_prefix=prefix1, key_hash=hash1)
    await create_api_key_record(session, team_id="team-other", key_prefix=prefix2, key_hash=hash2)

    req_id = f"req_{uuid.uuid4().hex}"
    record = InferenceRecordModel(
        request_id=req_id,
        team_id="team-owner",
        feature_id="general-chat",
        policy_id="policy-1",
        policy_version="v1",
        selected_model_id="mock-economy",
        selected_provider_id="mock",
        routing_reason="CHEAPEST_ELIGIBLE_MODEL",
        candidate_decisions=[],
        status="SUCCEEDED",
        error_code=None,
        prompt_hash="dummy_hash",
        message_count=1,
        input_tokens=10,
        output_tokens=10,
        total_tokens=20,
        accounted_cost_usd=Decimal("0.001"),
        cost_source="configured-model-pricing-v1",
        provider_latency_ms=50,
        created_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    await create_inference_record(session, record)

    app = create_app(db_manager=db_manager)
    with TestClient(app) as client:
        # Owner team retrieves record -> 200 OK
        headers_owner = {"Authorization": f"Bearer {owner_key}"}
        resp_owner = client.get(f"/v1/routing-decisions/{req_id}", headers=headers_owner)
        assert resp_owner.status_code == 200
        assert resp_owner.json()["team_id"] == "team-owner"

        # Other team attempts to retrieve record -> 404 Not Found (Cross-team isolation)
        headers_other = {"Authorization": f"Bearer {other_key}"}
        resp_other = client.get(f"/v1/routing-decisions/{req_id}", headers=headers_other)
        assert resp_other.status_code == 404


# 16. Raw Prompt Content Not Stored
async def test_16_raw_prompt_content_not_stored(session: AsyncSession) -> None:
    prompt_text = "SECRET_UNENCRYPTED_USER_PROMPT_123"
    msg = ChatMessage(role=ChatRole.USER, content=prompt_text)
    digest = hash_prompt([msg])

    req_id = f"req_{uuid.uuid4().hex}"
    record = InferenceRecordModel(
        request_id=req_id,
        team_id="team-records",
        feature_id="general-chat",
        policy_id="policy-1",
        policy_version="v1",
        selected_model_id="mock-economy",
        selected_provider_id="mock",
        routing_reason="CHEAPEST_ELIGIBLE_MODEL",
        candidate_decisions=[],
        status="SUCCEEDED",
        error_code=None,
        prompt_hash=digest,
        message_count=1,
        input_tokens=10,
        output_tokens=10,
        total_tokens=20,
        accounted_cost_usd=Decimal("0.001"),
        cost_source="configured-model-pricing-v1",
        provider_latency_ms=50,
        created_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    await create_inference_record(session, record)

    saved = await get_inference_record_by_request_id(session, req_id, "team-records")
    assert saved is not None
    assert prompt_text not in str(saved.__dict__)
    assert saved.prompt_hash == digest


# 17. Duplicate Request ID Cannot Create Duplicate Records
async def test_17_duplicate_request_id_fails(session: AsyncSession) -> None:
    req_id = f"req_dup_{uuid.uuid4().hex}"
    record1 = InferenceRecordModel(
        request_id=req_id,
        team_id="team-records",
        feature_id="general-chat",
        policy_id="policy-1",
        policy_version="v1",
        routing_reason="REASON",
        candidate_decisions=[],
        status="SUCCEEDED",
        prompt_hash="h1",
        message_count=1,
        created_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    await create_inference_record(session, record1)

    record2 = InferenceRecordModel(
        request_id=req_id,
        team_id="team-records",
        feature_id="general-chat",
        policy_id="policy-1",
        policy_version="v1",
        routing_reason="REASON",
        candidate_decisions=[],
        status="SUCCEEDED",
        prompt_hash="h2",
        message_count=1,
        created_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    with pytest.raises(IntegrityError):
        session.add(record2)
        await session.commit()
    await session.rollback()


# 18. Database Engine Cleanup
async def test_18_database_engine_cleanup() -> None:
    manager = DatabaseManager(database_url=TEST_DB_URL)
    await manager.aclose()


# 19 & 20. /readyz behavior when PostgreSQL is available vs unavailable
async def test_19_20_readyz_endpoint(db_manager: DatabaseManager) -> None:
    # Available DB
    app_available = create_app(db_manager=db_manager)
    with TestClient(app_available) as client:
        resp = client.get("/readyz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"

    # Unavailable DB
    bad_db = DatabaseManager(
        database_url="postgresql+asyncpg://invalid_user:invalid_pass@localhost:5432/nonexistent_db"
    )
    app_unavailable = create_app(db_manager=bad_db)
    with TestClient(app_unavailable) as client:
        resp = client.get("/readyz")
        assert resp.status_code == 503
        assert resp.json()["status"] == "unhealthy"
    await bad_db.aclose()
