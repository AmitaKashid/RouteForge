"""Unit tests for provider interfaces protocol."""

from typing import Protocol, runtime_checkable

from routeforge.providers import DeterministicMockProvider, LLMProvider


@runtime_checkable
class _RuntimeCheckableLLMProvider(LLMProvider, Protocol):
    pass


def test_provider_protocol_runtime_check() -> None:
    provider = DeterministicMockProvider()
    assert isinstance(provider, _RuntimeCheckableLLMProvider)
    assert provider.provider_id == "mock"
