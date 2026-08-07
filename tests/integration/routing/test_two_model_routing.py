"""Integration tests for Task M3.2 measured two-model Ollama routing."""

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from routeforge.contracts import (
    CandidateRejectionReason,
    Capability,
    ChatMessage,
    ChatRole,
    FallbackPolicy,
    FeatureId,
    FeaturePolicy,
    GovernanceClassification,
    ModelId,
    OutputFormat,
    PolicyId,
    PolicyStatus,
    PolicyVersion,
    ProviderId,
    ProviderOperatingState,
    RequestId,
    RoutingConstraints,
    TeamId,
    utc_now,
)
from routeforge.contracts.inference import ChatRequest
from routeforge.evaluation import (
    load_model_profile_registry_file,
)
from routeforge.gateway.app import create_app
from routeforge.gateway.auth import get_authenticated_team_id
from routeforge.gateway.estimation import build_candidate_estimate
from routeforge.gateway.runtime import GatewayRuntimeSettings
from routeforge.providers import OllamaProvider, OllamaProviderConfig
from routeforge.registries import (
    FeaturePolicyRegistry,
    InMemoryFeaturePolicyRegistry,
    ModelRegistry,
    load_registry_snapshot,
)
from routeforge.routing.eligibility import evaluate_candidate
from routeforge.routing.selection import RoutingCandidate, route_request


def load_dev_snapshot() -> tuple[ModelRegistry, FeaturePolicyRegistry]:
    snapshot = load_registry_snapshot(
        models_directory=Path("config/models"),
        policies_directory=Path("config/policies"),
    )
    return snapshot.models, snapshot.policies


def make_test_request(
    request_id_str: str = "r1",
    feature_id_str: str = "general-chat",
    messages: tuple[ChatMessage, ...] = (ChatMessage(role=ChatRole.USER, content="Hello"),),
) -> ChatRequest:
    return ChatRequest(
        request_id=RequestId(request_id_str),
        team_id=TeamId("local-dev"),
        feature_id=FeatureId(feature_id_str),
        messages=messages,
        output_format=OutputFormat.TEXT,
        routing_constraints=RoutingConstraints(),
        created_at=datetime.now(UTC),
    )


def test_1_two_ollama_model_definitions_load() -> None:
    models, _ = load_dev_snapshot()
    economy = models.get(ModelId("ollama-economy"))
    quality = models.get(ModelId("ollama-quality"))

    assert economy is not None
    assert quality is not None
    assert economy.model_id == ModelId("ollama-economy")
    assert quality.model_id == ModelId("ollama-quality")


def test_2_both_models_use_same_provider_adapter() -> None:
    models, _ = load_dev_snapshot()
    economy = models.get(ModelId("ollama-economy"))
    quality = models.get(ModelId("ollama-quality"))

    assert economy is not None and quality is not None
    assert economy.provider_id == ProviderId("ollama")
    assert quality.provider_id == ProviderId("ollama")


def test_3_model_profiles_parsed_and_versioned() -> None:
    path = Path("config/profiles/routing-profile-v1.json")
    assert path.is_file()
    registry = load_model_profile_registry_file(path)
    assert registry.profile_version == "routing-profile-v1"
    assert ModelId("ollama-economy") in registry.profiles
    assert ModelId("ollama-quality") in registry.profiles


def test_4_missing_task_profile_handled_explicitly() -> None:
    path = Path("config/profiles/routing-profile-v1.json")
    registry = load_model_profile_registry_file(path)

    req = make_test_request(feature_id_str="nonexistent-task")
    models, _ = load_dev_snapshot()
    economy = models.get(ModelId("ollama-economy"))
    assert economy is not None

    est = build_candidate_estimate(
        request=req,
        model=economy,
        feature_id=FeatureId("nonexistent-task"),
        model_profile_registry=registry,
    )
    assert est.predicted_quality == 0.0
    assert est.quality_provenance.source == "measured-profile-missing"


def test_7_lower_cost_model_wins_when_both_satisfy_quality() -> None:
    models, policies = load_dev_snapshot()
    policy = policies.get_active_for_feature(FeatureId("general-chat"))
    assert policy is not None

    profile_path = Path("config/profiles/routing-profile-v1.json")
    profile_registry = load_model_profile_registry_file(profile_path)

    req = make_test_request(
        request_id_str="r_cls",
        messages=(ChatMessage(role=ChatRole.USER, content="Classify sentiment: POSITIVE"),),
    )

    now = utc_now()
    candidate_models = [
        models.get(ModelId("ollama-economy")),
        models.get(ModelId("ollama-quality")),
    ]

    candidates = [
        RoutingCandidate(
            model=m,
            estimate=build_candidate_estimate(
                request=req,
                model=m,
                feature_id=FeatureId("classification"),
                model_profile_registry=profile_registry,
            ),
            provider_state=ProviderOperatingState.HEALTHY,
        )
        for m in candidate_models
        if m is not None
    ]

    decision = route_request(request=req, policy=policy, candidates=candidates, decided_at=now)
    assert decision.selected_model_id == ModelId("ollama-economy")


def test_8_stronger_model_wins_when_economy_below_quality_threshold() -> None:
    models, policies = load_dev_snapshot()
    policy = policies.get_active_for_feature(FeatureId("general-chat"))
    assert policy is not None

    profile_path = Path("config/profiles/routing-profile-v1.json")
    profile_registry = load_model_profile_registry_file(profile_path)

    req = make_test_request(
        request_id_str="r_sum",
        messages=(ChatMessage(role=ChatRole.USER, content="Summarize document"),),
    )

    now = utc_now()
    candidate_models = [
        models.get(ModelId("ollama-economy")),
        models.get(ModelId("ollama-quality")),
    ]

    candidates = [
        RoutingCandidate(
            model=m,
            estimate=build_candidate_estimate(
                request=req,
                model=m,
                feature_id=FeatureId("summarization"),
                model_profile_registry=profile_registry,
            ),
            provider_state=ProviderOperatingState.HEALTHY,
        )
        for m in candidate_models
        if m is not None
    ]

    decision = route_request(request=req, policy=policy, candidates=candidates, decided_at=now)
    assert decision.selected_model_id == ModelId("ollama-quality")


def test_9_latency_constraints_reject_slower_model() -> None:
    models, _ = load_dev_snapshot()
    quality = models.get(ModelId("ollama-quality"))
    assert quality is not None

    strict_policy = FeaturePolicy(
        policy_id=PolicyId("strict-lat-policy"),
        version=PolicyVersion("v1"),
        feature_id=FeatureId("general-chat"),
        status=PolicyStatus.ACTIVE,
        allowed_model_ids=(ModelId("ollama-quality"),),
        required_capabilities=(Capability.TEXT_CHAT,),
        minimum_quality=0.7,
        maximum_latency_ms=200,  # Quality model latency is 280ms
        maximum_estimated_cost_usd=Decimal("5.0"),
        maximum_governance_classification=quality.governance_allowed[0],
        allow_degraded_providers=False,
        fallback_policy=FallbackPolicy(enabled=False, maximum_fallback_attempts=0),
        created_at=datetime.now(UTC),
    )

    profile_path = Path("config/profiles/routing-profile-v1.json")
    profile_registry = load_model_profile_registry_file(profile_path)

    req = make_test_request()
    est = build_candidate_estimate(
        request=req,
        model=quality,
        feature_id=FeatureId("classification"),
        model_profile_registry=profile_registry,
    )

    eval_result = evaluate_candidate(
        request=req,
        policy=strict_policy,
        model=quality,
        estimate=est,
        provider_state=ProviderOperatingState.HEALTHY,
    )

    assert eval_result.eligible is False
    assert CandidateRejectionReason.LATENCY_ABOVE_TARGET in eval_result.rejection_reasons


def test_12_gateway_in_mock_mode_remains_unchanged() -> None:
    app = create_app(runtime_settings=GatewayRuntimeSettings(provider_mode="mock"))
    client = TestClient(app)

    req_body = {
        "model": "routeforge",
        "messages": [{"role": "user", "content": "Hello"}],
        "routeforge": {"feature_id": "general-chat"},
    }

    headers = {"Authorization": "Bearer rf_test_dev_key"}
    resp = client.post("/v1/chat/completions", json=req_body, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "chat.completion"
    assert data["routeforge"]["provider"] == "mock"


def test_13_14_gateway_in_ollama_mode_executes_selected_adapter_only() -> None:
    called_models: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read().decode("utf-8"))
        called_models.append(payload["model"])
        return httpx.Response(
            200,
            json={
                "model": payload["model"],
                "message": {"role": "assistant", "content": "Selected Ollama model response"},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 10,
                "eval_count": 5,
                "total_duration": 150_000_000,
            },
        )

    transport = httpx.MockTransport(handler)

    async def _run() -> None:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost:11434"
        ) as http_client:
            config = OllamaProviderConfig(
                model_names={
                    ModelId("ollama-economy"): "llama3.2:economy",
                    ModelId("ollama-quality"): "llama3.2:quality",
                }
            )
            ollama_provider = OllamaProvider(config=config, client=http_client)

            settings = GatewayRuntimeSettings(
                provider_mode="ollama",
                ollama_economy_model="llama3.2:economy",
                ollama_quality_model="llama3.2:quality",
            )

            models, _ = load_dev_snapshot()
            policy = FeaturePolicy(
                policy_id=PolicyId("ollama-policy"),
                version=PolicyVersion("v1"),
                feature_id=FeatureId("general-chat"),
                status=PolicyStatus.ACTIVE,
                allowed_model_ids=(ModelId("ollama-economy"), ModelId("ollama-quality")),
                required_capabilities=(Capability.TEXT_CHAT,),
                minimum_quality=0.7,
                maximum_latency_ms=2000,
                maximum_estimated_cost_usd=Decimal("5.0"),
                maximum_governance_classification=GovernanceClassification.RESTRICTED,
                allow_degraded_providers=False,
                fallback_policy=FallbackPolicy(enabled=False, maximum_fallback_attempts=0),
                created_at=datetime.now(UTC),
            )
            policy_reg = InMemoryFeaturePolicyRegistry([policy])

            app = create_app(
                model_registry=models,
                policy_registry=policy_reg,
                provider=ollama_provider,
                runtime_settings=settings,
            )
            app.dependency_overrides[get_authenticated_team_id] = lambda: TeamId("test-team")
            client = TestClient(app)

            req_body = {
                "model": "routeforge",
                "messages": [{"role": "user", "content": "Classify sentiment: Great app!"}],
                "routeforge": {"feature_id": "general-chat"},
            }

            headers = {"Authorization": "Bearer rf_test_dev_key"}
            resp = client.post("/v1/chat/completions", json=req_body, headers=headers)
            assert resp.status_code == 200, f"Unexpected error response: {resp.json()}"
            data = resp.json()
            assert data["model"] == "ollama-economy"
            assert data["routeforge"]["provider"] == "ollama"

            # Verify only the selected model was called
            assert called_models == ["llama3.2:economy"]

    asyncio.run(_run())
