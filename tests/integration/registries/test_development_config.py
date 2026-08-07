"""Integration test for committed repository configuration files in config/."""

from pathlib import Path

from routeforge.contracts import FeatureId, ModelId, PolicyStatus
from routeforge.registries import load_registry_snapshot


def test_load_committed_development_config() -> None:
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    models_dir = repo_root / "config" / "models"
    policies_dir = repo_root / "config" / "policies"

    snapshot = load_registry_snapshot(
        models_directory=models_dir,
        policies_directory=policies_dir,
    )

    models = snapshot.models.list_all()
    assert len(models) >= 2

    m_economy = snapshot.models.get(ModelId("mock-economy"))
    m_premium = snapshot.models.get(ModelId("mock-premium"))
    ollama_economy = snapshot.models.get(ModelId("ollama-economy"))
    ollama_quality = snapshot.models.get(ModelId("ollama-quality"))
    assert m_economy is not None
    assert m_premium is not None
    assert ollama_economy is not None
    assert ollama_quality is not None
    assert m_economy.provider_id == "mock"
    assert m_premium.provider_id == "mock"
    assert ollama_economy.provider_id == "ollama"
    assert ollama_quality.provider_id == "ollama"

    policies = snapshot.policies.list_all()
    assert len(policies) == 1

    active_policy = snapshot.policies.get_active_for_feature(FeatureId("general-chat"))
    assert active_policy is not None
    assert active_policy.status == PolicyStatus.ACTIVE
    assert ModelId("mock-economy") in active_policy.allowed_model_ids
    assert ModelId("mock-premium") in active_policy.allowed_model_ids
