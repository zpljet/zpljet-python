"""Typed errors for the ZPLJet API."""

from __future__ import annotations

from typing import Any

__all__ = [
    "APIConnectionError",
    "APIError",
    "APITimeoutError",
    "AuthenticationError",
    "BadRequestError",
    "ConversionFailedError",
    "PayloadTooLargeError",
    "PermissionDeniedError",
    "QuotaExceededError",
    "RateLimitError",
    "ServiceUnavailableError",
    "ZplJetError",
]


class ZplJetError(Exception):
    """Base class for every error raised by this SDK."""


class APIConnectionError(ZplJetError):
    """A network failure prevented a usable response."""

    def __init__(self, message: str = "Connection error") -> None:
        super().__init__(message)


class APITimeoutError(APIConnectionError):
    """A single attempt exceeded the configured timeout."""

    def __init__(self, message: str = "Request timed out") -> None:
        super().__init__(message)


class APIError(ZplJetError):
    """An HTTP error response from the API."""

    status: int
    """HTTP status code."""

    code: str | None
    """Stable machine-readable code — safe to branch on."""

    doc_url: str | None
    """Link to the docs entry for this code."""

    raw: dict[str, Any]
    """The raw parsed ``error`` object, including any context fields."""

    def __init__(self, status: int, message: str, raw: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        raw = raw or {}
        self.status = status
        self.code = raw.get("code") if isinstance(raw.get("code"), str) else None
        self.doc_url = raw.get("docUrl") if isinstance(raw.get("docUrl"), str) else None
        self.raw = raw

    @property
    def message(self) -> str:
        """The human-readable error message (may change; don't parse it)."""
        return str(self.args[0]) if self.args else ""

    @staticmethod
    def from_response(status: int, raw: dict[str, Any]) -> APIError:
        """Build the most specific error subclass for a response."""
        message = raw.get("message")
        if not isinstance(message, str) or not message:
            message = f"HTTP {status} error from the ZPLJet API"
        cls = _ERROR_CLASSES.get(str(raw.get("code")), APIError)
        return cls(status, message, raw)


class BadRequestError(APIError):
    """400 ``invalid_request`` response."""

    def __init__(self, status: int, message: str, raw: dict[str, Any] | None = None) -> None:
        super().__init__(status, message, raw)
        self.param: str | None = _str_field(self.raw, "param")
        """Dot-path of the invalid field, e.g. ``"zpl"`` or ``"dpmm"``."""


class AuthenticationError(APIError):
    """401 ``missing_api_key`` or ``invalid_api_key`` response."""


class PayloadTooLargeError(APIError):
    """413 ``payload_too_large`` — request body exceeded the API limit."""


class QuotaExceededError(APIError):
    """402 ``quota_exceeded`` — the monthly conversion quota is used up."""

    def __init__(self, status: int, message: str, raw: dict[str, Any] | None = None) -> None:
        super().__init__(status, message, raw)
        self.plan: str | None = _str_field(self.raw, "plan")
        """Plan id the account is on (e.g. ``"free"``)."""
        self.quota: int | None = _int_field(self.raw, "quota")
        """Monthly quota for that plan."""
        self.used: int | None = _int_field(self.raw, "used")
        """Conversions used so far this month."""
        self.resets_at: str | None = _str_field(self.raw, "resetsAt")
        """ISO 8601 UTC timestamp — when the quota resets."""


class PermissionDeniedError(APIError):
    """403 ``hosting_not_allowed`` or ``no_retention_enforced`` response."""


class RateLimitError(APIError):
    """429 ``rate_limit_exceeded`` response."""

    def __init__(self, status: int, message: str, raw: dict[str, Any] | None = None) -> None:
        super().__init__(status, message, raw)
        self.retry_after: float | None = _num_field(self.raw, "retryAfter")
        """Seconds to wait before retrying."""
        self.retry_at: str | None = _str_field(self.raw, "retryAt")
        """ISO 8601 UTC timestamp — when to retry."""


class ConversionFailedError(APIError):
    """502 ``conversion_failed`` response."""

    def __init__(self, status: int, message: str, raw: dict[str, Any] | None = None) -> None:
        super().__init__(status, message, raw)
        self.conversion_id: str | None = _str_field(self.raw, "conversionId")
        """Id of the failed attempt — quote it when contacting support."""


class ServiceUnavailableError(APIError):
    """503 ``service_unavailable`` response."""

    def __init__(self, status: int, message: str, raw: dict[str, Any] | None = None) -> None:
        super().__init__(status, message, raw)
        self.retry_after: float | None = _num_field(self.raw, "retryAfter")
        """Seconds to wait before retrying."""


_ERROR_CLASSES: dict[str, type[APIError]] = {
    "invalid_request": BadRequestError,
    "missing_api_key": AuthenticationError,
    "invalid_api_key": AuthenticationError,
    "payload_too_large": PayloadTooLargeError,
    "quota_exceeded": QuotaExceededError,
    "hosting_not_allowed": PermissionDeniedError,
    "no_retention_enforced": PermissionDeniedError,
    "rate_limit_exceeded": RateLimitError,
    "conversion_failed": ConversionFailedError,
    "service_unavailable": ServiceUnavailableError,
}


def _str_field(raw: dict[str, Any], key: str) -> str | None:
    value = raw.get(key)
    return value if isinstance(value, str) else None


def _int_field(raw: dict[str, Any], key: str) -> int | None:
    value = raw.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _num_field(raw: dict[str, Any], key: str) -> float | None:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
