"""Runtime environment setup and provider manager for RouteForge Gateway."""

import os
from dataclasses import dataclass
from pathlib import Path

from routeforge.contracts import ModelId, ProviderId
from routeforge.evaluation.model_profiles import (
    ModelProfileRegistry,
    load_model_profile_registry_file,
)
from routeforge.providers.interfaces import LLMProvider
from routeforge.providers.mock import DeterministicMockProvider
from routeforge.providers.ollama import OllamaProvider, OllamaProviderConfig


@dataclass(frozen=True, slots=True)
class GatewayRuntimeSettings:
    """Configuration settings for gateway execution mode."""

    provider_mode: str = "mock"  # "mock" or "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_economy_model: str = "llama3.2:latest"
    ollama_quality_model: str = "llama3.2:latest"
    profile_path: str = "config/profiles/routing-profile-v1.json"

    @classmethod
    def from_environment(cls) -> "GatewayRuntimeSettings":
        """Load settings from environment variables with sensible defaults."""
        return cls(
            provider_mode=os.getenv("ROUTEFORGE_PROVIDER_MODE", "mock").lower(),
            ollama_base_url=os.getenv("ROUTEFORGE_OLLAMA_BASE_URL", "http://localhost:11434"),
            ollama_economy_model=os.getenv("ROUTEFORGE_OLLAMA_ECONOMY_MODEL", "llama3.2:latest"),
            ollama_quality_model=os.getenv("ROUTEFORGE_OLLAMA_QUALITY_MODEL", "llama3.2:latest"),
            profile_path=os.getenv(
                "ROUTEFORGE_MODEL_PROFILE_PATH", "config/profiles/routing-profile-v1.json"
            ),
        )


class GatewayRuntimeManager:
    """Manages active providers and measured model profiles according to runtime mode."""

    def __init__(self, settings: GatewayRuntimeSettings | None = None) -> None:
        self.settings = settings or GatewayRuntimeSettings.from_environment()
        self.profile_registry: ModelProfileRegistry | None = None
        self._providers: dict[str, LLMProvider] = {}
        self._initialize()

    def _initialize(self) -> None:
        prof_file = Path(self.settings.profile_path)
        if prof_file.is_file():
            try:
                self.profile_registry = load_model_profile_registry_file(prof_file)
            except Exception:
                self.profile_registry = None

        if self.settings.provider_mode == "ollama":
            config = OllamaProviderConfig(
                base_url=self.settings.ollama_base_url,
                model_names={
                    ModelId("ollama-economy"): self.settings.ollama_economy_model,
                    ModelId("ollama-quality"): self.settings.ollama_quality_model,
                },
            )
            self.register_provider("ollama", OllamaProvider(config=config))
        else:
            self.register_provider("mock", DeterministicMockProvider())

    def register_provider(self, provider_id: str | ProviderId, provider: LLMProvider) -> None:
        """Register a provider instance for a provider ID."""
        key = str(provider_id).lower()
        self._providers[key] = provider

    def get_provider(self, provider_id_str: str) -> LLMProvider:
        """Retrieve provider instance by provider ID."""
        key = provider_id_str.lower()
        if key in self._providers:
            return self._providers[key]
        if "mock" in self._providers:
            return self._providers["mock"]
        if self._providers:
            return next(iter(self._providers.values()))
        raise ValueError(f"No registered provider found for provider ID '{provider_id_str}'.")

    async def aclose(self) -> None:
        """Close provider resources."""
        for provider in self._providers.values():
            if hasattr(provider, "aclose"):
                await provider.aclose()
