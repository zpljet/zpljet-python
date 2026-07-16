from __future__ import annotations

import json

import pytest
from conftest import ZPL, FakeTransport, error_response, hosted_response, pdf_response

import zpljet._client
from zpljet import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AsyncZplJet,
    AuthenticationError,
    BadRequestError,
    ConversionFailedError,
    PermissionDeniedError,
    QuotaExceededError,
    RateLimitError,
    TransportResponse,
    ZplJet,
    ZplJetError,
    __version__,
)


def make_client(transport: FakeTransport, **kwargs: object) -> ZplJet:
    options = {"max_retries": 0, **kwargs}
    return ZplJet("zpl_test", transport=transport, **options)  # type: ignore[arg-type]


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Stub out retry sleeps; returns the list of requested delays."""
    recorded: list[float] = []
    monkeypatch.setattr(zpljet._client, "_sleep", recorded.append)
    return recorded


class TestConstructor:
    def test_requires_an_api_key(self) -> None:
        with pytest.raises(ZplJetError, match="Missing API key"):
            ZplJet("   ")

    def test_applies_defaults(self) -> None:
        client = ZplJet("zpl_test")
        assert client.base_url == "https://api.zpljet.com"
        assert client.timeout == 60.0
        assert client.max_retries == 2

    def test_validates_max_retries_and_caps_large_values(self) -> None:
        with pytest.raises(ValueError, match="max_retries"):
            ZplJet("zpl_test", max_retries=-1)
        with pytest.raises(ValueError, match="max_retries"):
            AsyncZplJet("zpl_test", max_retries=1.5)  # type: ignore[arg-type]
        assert ZplJet("zpl_test", max_retries=99).max_retries == 10

    def test_strips_trailing_slashes_from_base_url(self) -> None:
        client = ZplJet("zpl_test", base_url="http://localhost:3000//")
        assert client.base_url == "http://localhost:3000"

    def test_rejects_plaintext_remote_base_url_without_opt_in(self) -> None:
        with pytest.raises(ZplJetError, match="plaintext"):
            ZplJet("zpl_test", base_url="http://api.example.com")
        ZplJet(
            "zpl_test",
            base_url="http://api.example.com",
            allow_insecure_http=True,
        )


class TestRequestShape:
    def test_posts_json_with_api_key_and_user_agent(self) -> None:
        transport = FakeTransport(pdf_response())
        make_client(transport).convert(zpl=ZPL, dpmm=12, format="pdf")

        assert len(transport.calls) == 1
        url, body, headers, timeout = transport.calls[0]
        assert url == "https://api.zpljet.com/v1/convert"
        assert headers["Content-Type"] == "application/json"
        assert headers["X-API-Key"] == "zpl_test"
        assert headers["User-Agent"] == f"zpljet-python/{__version__}"
        assert timeout == 60.0
        assert json.loads(body) == {"zpl": ZPL, "dpmm": 12, "format": "pdf"}

    def test_omits_unset_parameters(self) -> None:
        transport = FakeTransport(pdf_response())
        make_client(transport).convert(zpl=ZPL)
        assert json.loads(transport.calls[0][1]) == {"zpl": ZPL}

    def test_per_request_timeout_override(self) -> None:
        transport = FakeTransport(pdf_response())
        make_client(transport).convert(zpl=ZPL, timeout=5.0)
        assert transport.calls[0][3] == 5.0


class TestDataMode:
    def test_returns_bytes_content_type_and_id(self) -> None:
        transport = FakeTransport(pdf_response("conv_abc", b"%PDF-1.7"))
        label = make_client(transport).convert(zpl=ZPL)

        assert label.data == b"%PDF-1.7"
        assert label.content_type == "application/pdf"
        assert label.id == "conv_abc"


class TestUrlMode:
    def test_returns_parsed_hosted_label(self) -> None:
        transport = FakeTransport(hosted_response(pages=2, retentionDays=7))
        hosted = make_client(transport).convert(zpl=ZPL, output="url")

        assert hosted.url.startswith("https://")
        assert hosted.pages == 2
        assert hosted.retention_days == 7
        assert hosted.id == "conv_456"
        assert hosted.expires_at == "2026-07-10T00:00:00.000Z"

    def test_rejects_malformed_hosted_payload_without_retrying(self) -> None:
        transport = FakeTransport(
            TransportResponse(
                200,
                {"content-type": "application/json"},
                b'{"id":"conv_456"}',
            )
        )

        with pytest.raises(ZplJetError, match="Invalid"):
            make_client(transport, max_retries=5).convert(zpl=ZPL, output="url")
        assert len(transport.calls) == 1


class TestErrorMapping:
    def test_400_bad_request_with_param(self) -> None:
        transport = FakeTransport(
            error_response(400, "invalid_request", "zpl: no ^XA…^XZ label found", param="zpl")
        )
        with pytest.raises(BadRequestError) as info:
            make_client(transport).convert(zpl="nope")

        assert info.value.status == 400
        assert info.value.code == "invalid_request"
        assert info.value.param == "zpl"
        assert info.value.doc_url == "https://zpljet.com/docs/errors#invalid_request"

    def test_401_authentication_error(self) -> None:
        transport = FakeTransport(error_response(401, "invalid_api_key"))
        with pytest.raises(AuthenticationError):
            make_client(transport).convert(zpl=ZPL)

    def test_402_quota_exceeded_with_context(self) -> None:
        transport = FakeTransport(
            error_response(
                402,
                "quota_exceeded",
                "Monthly quota exceeded",
                plan="free",
                quota=500,
                used=500,
                resetsAt="2026-08-01T00:00:00.000Z",
            )
        )
        with pytest.raises(QuotaExceededError) as info:
            make_client(transport).convert(zpl=ZPL)

        assert info.value.plan == "free"
        assert info.value.quota == 500
        assert info.value.used == 500
        assert info.value.resets_at == "2026-08-01T00:00:00.000Z"

    def test_403_permission_denied_code_distinguishes_cause(self) -> None:
        transport = FakeTransport(error_response(403, "hosting_not_allowed"))
        with pytest.raises(PermissionDeniedError) as info:
            make_client(transport).convert(zpl=ZPL, output="url")
        assert info.value.code == "hosting_not_allowed"

    def test_502_conversion_failed_never_retried(self, sleeps: list[float]) -> None:
        transport = FakeTransport(
            error_response(502, "conversion_failed", "Could not render", conversionId="conv_x")
        )
        with pytest.raises(ConversionFailedError) as info:
            make_client(transport, max_retries=5).convert(zpl=ZPL)

        assert info.value.conversion_id == "conv_x"
        assert len(transport.calls) == 1
        assert sleeps == []

    def test_unknown_code_plain_api_error_with_raw(self) -> None:
        transport = FakeTransport(error_response(418, "future_code", "??", extra=1))
        with pytest.raises(APIError) as info:
            make_client(transport).convert(zpl=ZPL)

        assert type(info.value) is APIError
        assert info.value.status == 418
        assert info.value.raw["extra"] == 1

    def test_non_json_error_body_gets_default_message(self) -> None:
        transport = FakeTransport(
            TransportResponse(status=503, headers={}, body=b"<html>Bad Gateway</html>")
        )
        with pytest.raises(APIError, match="HTTP 503") as info:
            make_client(transport).convert(zpl=ZPL)
        assert info.value.status == 503

    def test_all_api_errors_extend_zpljet_error(self) -> None:
        transport = FakeTransport(error_response(401, "missing_api_key"))
        with pytest.raises(ZplJetError):
            make_client(transport).convert(zpl=ZPL)


class TestRetries:
    def test_retries_a_429_and_succeeds(self, sleeps: list[float]) -> None:
        transport = FakeTransport(
            error_response(429, "rate_limit_exceeded", "slow down", retryAfter=0),
            pdf_response(),
        )
        label = make_client(transport, max_retries=2).convert(zpl=ZPL)

        assert label.content_type == "application/pdf"
        assert len(transport.calls) == 2

    def test_honors_retry_after(self, sleeps: list[float]) -> None:
        transport = FakeTransport(
            error_response(429, "rate_limit_exceeded", "slow down", retryAfter=3),
            pdf_response(),
        )
        make_client(transport, max_retries=1).convert(zpl=ZPL)
        assert sleeps == [3.0]

    def test_raises_rate_limit_error_with_context_once_exhausted(
        self, sleeps: list[float]
    ) -> None:
        transport = FakeTransport(
            error_response(
                429,
                "rate_limit_exceeded",
                "slow down",
                retryAfter=0,
                retryAt="2026-07-07T00:00:01.000Z",
            )
        )
        with pytest.raises(RateLimitError) as info:
            make_client(transport, max_retries=2).convert(zpl=ZPL)

        assert info.value.retry_after == 0
        assert info.value.retry_at == "2026-07-07T00:00:01.000Z"
        assert len(transport.calls) == 3  # 1 attempt + 2 retries

    def test_retries_connection_errors_with_backoff(self, sleeps: list[float]) -> None:
        transport = FakeTransport(APIConnectionError("boom"), pdf_response())
        label = make_client(transport, max_retries=1).convert(zpl=ZPL)

        assert label.content_type == "application/pdf"
        assert len(transport.calls) == 2
        assert len(sleeps) == 1
        assert 0.5 <= sleeps[0] <= 0.625  # base backoff + up to 25% jitter

    def test_raises_connection_error_once_exhausted(self, sleeps: list[float]) -> None:
        transport = FakeTransport(APIConnectionError("boom"))
        with pytest.raises(APIConnectionError):
            make_client(transport, max_retries=1).convert(zpl=ZPL)
        assert len(transport.calls) == 2

    def test_retries_timeouts_like_any_connection_error(self, sleeps: list[float]) -> None:
        transport = FakeTransport(APITimeoutError("slow"), APITimeoutError("slow"))
        with pytest.raises(APITimeoutError):
            make_client(transport, max_retries=1).convert(zpl=ZPL)
        assert len(transport.calls) == 2

    def test_retries_transient_5xx_without_structured_body(self, sleeps: list[float]) -> None:
        transport = FakeTransport(
            TransportResponse(status=500, headers={}, body=b"oops"), pdf_response()
        )
        label = make_client(transport, max_retries=1).convert(zpl=ZPL)
        assert label.content_type == "application/pdf"

    def test_max_retries_0_fails_on_first_error(self, sleeps: list[float]) -> None:
        transport = FakeTransport(
            error_response(429, "rate_limit_exceeded", "slow down", retryAfter=0)
        )
        with pytest.raises(RateLimitError):
            make_client(transport).convert(zpl=ZPL)
        assert len(transport.calls) == 1

    def test_per_request_max_retries_overrides_client_default(
        self, sleeps: list[float]
    ) -> None:
        transport = FakeTransport(
            error_response(429, "rate_limit_exceeded", "slow down", retryAfter=0),
            pdf_response(),
        )
        label = make_client(transport, max_retries=0).convert(zpl=ZPL, max_retries=1)
        assert label.id == "conv_123"

    def test_never_retries_4xx_client_errors(self, sleeps: list[float]) -> None:
        transport = FakeTransport(error_response(400, "invalid_request", "bad", param="zpl"))
        with pytest.raises(BadRequestError):
            make_client(transport, max_retries=5).convert(zpl="x")
        assert len(transport.calls) == 1

    def test_retry_after_is_capped(self, sleeps: list[float]) -> None:
        transport = FakeTransport(
            error_response(429, "rate_limit_exceeded", "slow down", retryAfter=9999),
            pdf_response(),
        )
        make_client(transport, max_retries=1).convert(zpl=ZPL)
        assert sleeps == [30.0]


class TestAsyncClient:
    async def test_same_interface_and_results(self) -> None:
        transport = FakeTransport(pdf_response("conv_async"))
        client = AsyncZplJet("zpl_test", transport=transport, max_retries=0)
        label = await client.convert(zpl=ZPL)

        assert label.id == "conv_async"
        assert label.content_type == "application/pdf"

    async def test_url_mode(self) -> None:
        transport = FakeTransport(hosted_response())
        client = AsyncZplJet("zpl_test", transport=transport, max_retries=0)
        hosted = await client.convert(zpl=ZPL, output="url")
        assert hosted.url.startswith("https://")

    async def test_errors_propagate(self) -> None:
        transport = FakeTransport(error_response(401, "invalid_api_key"))
        client = AsyncZplJet("zpl_test", transport=transport, max_retries=0)
        with pytest.raises(AuthenticationError):
            await client.convert(zpl=ZPL)
