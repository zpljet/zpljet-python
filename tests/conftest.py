"""Shared test helpers — a scriptable fake transport, no network involved."""

from __future__ import annotations

import json
from collections.abc import Mapping

from zpljet import TransportResponse

ZPL = "^XA^FO50,50^A0N,50,50^FDHello^FS^XZ"


class FakeTransport:
    """Serves the given results in order (repeating the last one). Exception
    instances are raised instead of returned (transport failures)."""

    def __init__(self, *results: TransportResponse | Exception) -> None:
        self._results = list(results)
        self._index = 0
        self.calls: list[tuple[str, bytes, Mapping[str, str], float]] = []

    def __call__(
        self, url: str, body: bytes, headers: Mapping[str, str], timeout: float
    ) -> TransportResponse:
        self.calls.append((url, body, headers, timeout))
        result = self._results[min(self._index, len(self._results) - 1)]
        self._index += 1
        if isinstance(result, Exception):
            raise result
        return result


def error_response(
    status: int, code: str, message: str = "message", **context: object
) -> TransportResponse:
    """A structured API error response, exactly as the server builds them."""
    payload = {
        "error": {
            "code": code,
            "message": message,
            **context,
            "docUrl": f"https://zpljet.com/docs/errors#{code}",
        }
    }
    return TransportResponse(
        status=status,
        headers={"Content-Type": "application/json"},
        body=json.dumps(payload).encode(),
    )


def pdf_response(conversion_id: str = "conv_123", body: bytes = b"%PDF-fake") -> TransportResponse:
    """A successful ``output="data"`` response carrying PDF bytes."""
    return TransportResponse(
        status=200,
        headers={"Content-Type": "application/pdf", "X-Conversion-Id": conversion_id},
        body=body,
    )


def hosted_response(**overrides: object) -> TransportResponse:
    """A successful ``output="url"`` JSON response."""
    payload: dict[str, object] = {
        "id": "conv_456",
        "url": "https://files.example/conv_456.pdf",
        "pages": 1,
        "retentionDays": 3,
        "expiresAt": "2026-07-10T00:00:00.000Z",
        **overrides,
    }
    return TransportResponse(
        status=200,
        headers={"Content-Type": "application/json"},
        body=json.dumps(payload).encode(),
    )
