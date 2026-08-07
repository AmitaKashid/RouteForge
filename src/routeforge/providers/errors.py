"""Provider execution exception wrapper for domain error contracts."""

from routeforge.contracts import ProviderError


class ProviderExecutionError(Exception):
    """Raised when an attempt fails at the provider execution boundary."""

    def __init__(self, error: ProviderError) -> None:
        self._error = error
        super().__init__(
            f"Provider '{error.provider_id}' execution failed [{error.code}]: {error.message}"
        )

    @property
    def error(self) -> ProviderError:
        """Return the wrapped immutable ProviderError domain contract."""
        return self._error
