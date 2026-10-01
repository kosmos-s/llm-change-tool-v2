"""Distinguish source errors, provider failures and unknown paid outcomes."""

from llm_change_tool.providers.base import ProviderFailure


def classify_failure(exc=None, *, code=None, phase="provider"):
    if code is None:
        code = str(exc) if isinstance(exc, ProviderFailure) else type(exc).__name__
    if phase == "images":
        return "data", code, False, False
    if code in ("http_400", "http_401", "http_403", "http_404", "http_422", "insufficient_quota"):
        return "configuration", code, False, True
    if code in ("interrupted_unknown_outcome", "missing_token_usage"):
        return "unknown_outcome", code, False, False
    if code in ("malformed_output", "refused_or_truncated"):
        return "ai_response", code, True, False
    if (
        (isinstance(exc, ProviderFailure) and exc.retryable)
        or code in ("connection_or_timeout", "http_429")
        or code.startswith("http_5")
    ):
        return "transient", code, True, False
    return "provider", code, False, False
