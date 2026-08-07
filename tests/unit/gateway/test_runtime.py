"""Unit tests for GatewayRuntimeManager and GatewayRuntimeSettings."""

from pathlib import Path
from typing import Any

import pytest

from routeforge.contracts import ProviderId
from routeforge.gateway.runtime import GatewayRuntimeManager, GatewayRuntimeSettings
from routeforge.providers import DeterministicMockProvider, LLMProvider, OllamaProvider


def test_runtime_settings_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROUTEFORGE_PROVIDER_MODE", "ollama")
    monkeypatch.setenv("ROUTEFORGE_OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("ROUTEFORGE_OLLAMA_ECONOMY_MODEL", "llama3.2:economy")
    monkeypatch.setenv("ROUTEFORGE_OLLAMA_QUALITY_MODEL", "llama3.2:quality")
    monkeypatch.setenv("ROUTEFORGE_MODEL_PROFILE_PATH", "nonexistent.json")

    settings = GatewayRuntimeSettings.from_environment()
    assert settings.provider_mode == "ollama"
    assert settings.ollama_economy_model == "llama3.2:economy"
    assert settings.ollama_quality_model == "llama3.2:quality"


def test_runtime_manager_invalid_profile_fallback() -> None:
    settings = GatewayRuntimeSettings(profile_path="nonexistent_profile.json", provider_mode="mock")
    manager = GatewayRuntimeManager(settings=settings)
    assert manager.profile_registry is None
    p = manager.get_provider("mock")
    assert isinstance(p, DeterministicMockProvider)


def test_runtime_manager_get_provider_fallback() -> None:
    settings = GatewayRuntimeSettings(provider_mode="ollama")
    manager = GatewayRuntimeManager(settings=settings)
    p = manager.get_provider("ollama")
    assert isinstance(p, OllamaProvider)

    p_fallback = manager.get_provider("unknown_provider")
    assert p_fallback is p


def test_runtime_manager_invalid_json_profile_fallback(tmp_path: Path) -> None:
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("{ invalid json")
    settings = GatewayRuntimeSettings(profile_path=str(bad_file), provider_mode="mock")
    manager = GatewayRuntimeManager(settings=settings)
    assert manager.profile_registry is None


def test_runtime_manager_aclose_with_aclose_provider() -> None:
    import asyncio

    class CloseableProvider(LLMProvider):
        def __init__(self) -> None:
            self.closed = False

        @property
        def provider_id(self) -> ProviderId:
            return ProviderId("mock")

        async def complete(self, request: Any, model: Any) -> Any:
            pass

        async def aclose(self) -> None:
            self.closed = True

    settings = GatewayRuntimeSettings(provider_mode="mock")
    manager = GatewayRuntimeManager(settings=settings)
    closeable = CloseableProvider()
    manager.register_provider("mock", closeable)

    asyncio.run(manager.aclose())
    assert closeable.closed is True
