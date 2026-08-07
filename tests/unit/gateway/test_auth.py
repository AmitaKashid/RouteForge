"""Unit tests for storage helper functions, prompt hashing, and API key parsing."""

from decimal import Decimal

from routeforge.contracts import (
    Capability,
    ChatMessage,
    ChatRole,
    GovernanceClassification,
    ModelDefinition,
    ModelId,
    ProviderId,
    QualityProfile,
)
from routeforge.storage.records import (
    calculate_accounted_cost,
    generate_api_key,
    hash_api_key,
    hash_prompt,
    parse_api_key_prefix,
)


def test_generate_and_parse_api_key() -> None:
    full_key, prefix, key_hash = generate_api_key()
    assert full_key.startswith(f"rf_{prefix}_")
    assert parse_api_key_prefix(full_key) == prefix
    assert hash_api_key(full_key) == key_hash


def test_invalid_api_key_format() -> None:
    assert parse_api_key_prefix("invalid_key") is None
    assert parse_api_key_prefix("rf_prefixonly") is None
    assert parse_api_key_prefix("bearer_rf_123_456") is None


def test_hash_prompt_canonical() -> None:
    msgs = [
        ChatMessage(role=ChatRole.SYSTEM, content="You are a helpful assistant."),
        ChatMessage(role=ChatRole.USER, content="Hello!"),
    ]
    digest1 = hash_prompt(msgs)
    digest2 = hash_prompt(msgs)
    assert digest1 == digest2
    assert len(digest1) == 64  # SHA-256 hex string


def test_calculate_accounted_cost() -> None:
    qp = QualityProfile(
        task_type="general",
        predicted_quality=0.8,
        source="m2-estimator",
        version="v1",
    )
    model = ModelDefinition(
        model_id=ModelId("test-model"),
        provider_id=ProviderId("test-provider"),
        display_name="Test Model",
        capabilities=(Capability.TEXT_CHAT,),
        governance_allowed=(GovernanceClassification.PUBLIC,),
        context_window_tokens=8192,
        estimated_input_cost_per_million_tokens_usd=Decimal("1.00"),
        estimated_output_cost_per_million_tokens_usd=Decimal("2.00"),
        estimated_latency_ms=100,
        quality_profiles=(qp,),
        enabled=True,
        configuration_version="v1",
    )
    # 1000 input tokens = $0.001, 500 output tokens = $0.001 -> Total = $0.002
    cost = calculate_accounted_cost(model, input_tokens=1000, output_tokens=500)
    assert cost == Decimal("0.00200000")
