"""Tests for the default urllib transport's failure mapping — no network."""

from __future__ import annotations

import http.client
import io
import urllib.error
import urllib.request
from email.message import Message
from typing import IO, Any, ClassVar, cast

import pytest
from conftest import ZPL, FakeTransport, error_response, pdf_response

import zpljet._client
from zpljet import APIConnectionError, APITimeoutError, ZplJet
from zpljet._client import _parse_retry_after_header, _urllib_transport


class _FakeResponse:
    """Minimal stand-in for the object urlopen yields."""

    status = 200
    headers: ClassVar[dict[str, str]] = {}

    def __init__(self, read_exc: Exception) -> None:
        self._read_exc = read_exc

    def read(self) -> bytes:
        raise self._read_exc

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_incomplete_read_on_success_body_wraps_as_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exc = http.client.IncompleteRead(b"partial", expected=100)
    monkeypatch.setattr(
        zpljet._client._NO_REDIRECT_OPENER,
        "open",
        lambda *a, **k: _FakeResponse(exc),
    )
    with pytest.raises(APIConnectionError):
        _urllib_transport("https://api.example/v1/convert", b"{}", {}, 5.0)


def test_incomplete_read_on_error_body_wraps_as_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_http_error(*args: Any, **kwargs: Any) -> None:
        raise urllib.error.HTTPError(
            "https://api.example/v1/convert",
            502,
            "Bad Gateway",
            Message(),
            cast("IO[bytes]", _BrokenBody()),
        )

    class _BrokenBody(io.RawIOBase):
        def read(self, size: int = -1) -> bytes:
            raise http.client.IncompleteRead(b"", expected=10)

    monkeypatch.setattr(zpljet._client._NO_REDIRECT_OPENER, "open", raise_http_error)
    with pytest.raises(APIConnectionError):
        _urllib_transport("https://api.example/v1/convert", b"{}", {}, 5.0)


@pytest.mark.parametrize(
    "exc",
    [TimeoutError(), urllib.error.URLError(TimeoutError())],
    ids=["direct", "url-error"],
)
def test_timeouts_map_to_api_timeout(
    monkeypatch: pytest.MonkeyPatch, exc: Exception
) -> None:
    def raise_timeout(*args: Any, **kwargs: Any) -> None:
        raise exc

    monkeypatch.setattr(zpljet._client._NO_REDIRECT_OPENER, "open", raise_timeout)
    with pytest.raises(APITimeoutError):
        _urllib_transport("https://api.example/v1/convert", b"{}", {}, 5.0)


def test_default_transport_does_not_follow_redirects() -> None:
    handler = zpljet._client._NoRedirectHandler()
    request = urllib.request.Request("https://api.example/v1/convert")

    redirected = handler.redirect_request(
        request,
        object(),
        302,
        "Found",
        {},
        "https://attacker.example/collect",
    )

    assert redirected is None


def test_connection_errors_are_retried_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[float] = []
    monkeypatch.setattr(zpljet._client, "_sleep", recorded.append)
    transport = FakeTransport(APIConnectionError("mid-body drop"), pdf_response())
    client = ZplJet("zpl_test", transport=transport, max_retries=1)

    label = client.convert(zpl=ZPL)
    assert label.content_type == "application/pdf"
    assert len(transport.calls) == 2


class TestRetryAfterHeader:
    def test_parses_delta_seconds(self) -> None:
        assert _parse_retry_after_header("7") == 7.0
        assert _parse_retry_after_header("0") == 0.0

    def test_parses_http_date(self) -> None:
        value = _parse_retry_after_header("Tue, 07 Jul 2099 00:00:00 GMT")
        assert value is not None and value > 0

    def test_rejects_garbage(self) -> None:
        assert _parse_retry_after_header("soon") is None
        assert _parse_retry_after_header(None) is None
        assert _parse_retry_after_header("") is None

    def test_header_honored_when_body_is_not_json(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorded: list[float] = []
        monkeypatch.setattr(zpljet._client, "_sleep", recorded.append)
        from zpljet import TransportResponse

        gateway_429 = TransportResponse(
            status=429,
            headers={"Retry-After": "3", "Content-Type": "text/html"},
            body=b"<html>Too Many Requests</html>",
        )
        transport = FakeTransport(gateway_429, pdf_response())
        client = ZplJet("zpl_test", transport=transport, max_retries=1)

        label = client.convert(zpl=ZPL)
        assert label.content_type == "application/pdf"
        assert recorded == [3.0]

    def test_body_retry_after_takes_precedence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorded: list[float] = []
        monkeypatch.setattr(zpljet._client, "_sleep", recorded.append)
        response = error_response(429, "rate_limit_exceeded", "slow down", retryAfter=1)
        response = type(response)(
            status=response.status,
            headers={**dict(response.headers), "Retry-After": "60"},
            body=response.body,
        )
        transport = FakeTransport(response, pdf_response())
        client = ZplJet("zpl_test", transport=transport, max_retries=1)

        client.convert(zpl=ZPL)
        assert recorded == [1.0]
