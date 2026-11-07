"""Sanitized structured-provider failure."""
class ProviderUnavailable(Exception):
    """The provider could not produce an answer (every model failed, bad key, timeout...)."""

    def __init__(self, reason: str, *, diagnostics=()):
        super().__init__(reason)
        self.reason = reason
        self.diagnostics = tuple(diagnostics)
