from __future__ import annotations

import pytest

from zpljet import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    ConversionFailedError,
    PayloadTooLargeError,
    PermissionDeniedError,
    QuotaExceededError,
    RateLimitError,
    ServiceUnavailableError,
    ZplJetError,
)


@pytest.mark.parametrize(
    ("code", "cls"),
    [
        ("invalid_request", BadRequestError),
        ("missing_api_key", AuthenticationError),
        ("invalid_api_key", AuthenticationError),
        ("payload_too_large", PayloadTooLargeError),
        ("quota_exceeded", QuotaExceededError),
        ("hosting_not_allowed", PermissionDeniedError),
        ("no_retention_enforced", PermissionDeniedError),
        ("rate_limit_exceeded", RateLimitError),
        ("conversion_failed", ConversionFailedError),
        ("service_unavailable", ServiceUnavailableError),
    ],
)
def test_from_response_maps_codes(code: str, cls: type[APIError]) -> None:
    err = APIError.from_response(400, {"code": code, "message": "m"})
    assert isinstance(err, cls)
    assert err.code == code
    assert err.message == "m"


def test_falls_back_to_api_error_for_unknown_codes() -> None:
    err = APIError.from_response(500, {"code": "brand_new_code", "message": "m"})
    assert type(err) is APIError
    assert err.code == "brand_new_code"


def test_builds_default_message_when_body_has_none() -> None:
    err = APIError.from_response(500, {})
    assert err.message == "HTTP 500 error from the ZPLJet API"
    assert err.code is None


def test_keeps_full_raw_payload() -> None:
    raw = {"code": "quota_exceeded", "message": "m", "plan": "free", "surprise": True}
    err = APIError.from_response(402, raw)
    assert err.raw == raw


def test_ignores_context_fields_of_wrong_type() -> None:
    err = APIError.from_response(
        429, {"code": "rate_limit_exceeded", "message": "m", "retryAfter": "soon"}
    )
    assert isinstance(err, RateLimitError)
    assert err.retry_after is None


def test_every_error_extends_zpljet_error() -> None:
    for err in (
        APIError(500, "m"),
        APIConnectionError(),
        APITimeoutError(),
        APIError.from_response(400, {"code": "invalid_request", "message": "m"}),
    ):
        assert isinstance(err, ZplJetError)
        assert isinstance(err, Exception)


def test_timeout_is_a_connection_error() -> None:
    assert isinstance(APITimeoutError(), APIConnectionError)
