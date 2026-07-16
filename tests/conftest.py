"""Shared test helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping

from zpljet import TransportResponse

ZPL = "^XA^FO50,50^A0N,50,50^FDHello^FS^XZ"


class FakeTransport:
    """Serve scripted responses or exceptions in order."""

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
    """Build an API error response."""
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
    """Build a PDF response."""
    return TransportResponse(
        status=200,
        headers={"Content-Type": "application/pdf", "X-Conversion-Id": conversion_id},
        body=body,
    )


def hosted_response(**overrides: object) -> TransportResponse:
    """Build a hosted-label response."""
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
