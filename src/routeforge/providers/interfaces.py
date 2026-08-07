"""Provider-neutral LLM execution protocol."""

from typing import Protocol

from routeforge.contracts import ModelDefinition, ProviderId, ProviderRequest, ProviderResponse


class LLMProvider(Protocol):
    """Provider-neutral execution interface for single completion attempts."""

    @property
    def provider_id(self) -> ProviderId:
        """Return the unique provider identifier."""
        ...

    async def complete(
        self,
        request: ProviderRequest,
        model: ModelDefinition,
    ) -> ProviderResponse:
        """Execute one normalized completion attempt against a specified model."""
        ...
