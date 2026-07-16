"""End-to-end tests against a real ZPLJet API.

Skipped unless ZPLJET_API_KEY is set — they consume real quota::

    ZPLJET_API_KEY=zpl_… pytest tests/test_e2e.py

Point them at a local/staging stack with ZPLJET_BASE_URL (e.g.
http://localhost:3000).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from zpljet import (
    AsyncZplJet,
    AuthenticationError,
    BadRequestError,
    PermissionDeniedError,
    ZplJet,
)

API_KEY = os.environ.get("ZPLJET_API_KEY")
BASE_URL = os.environ.get("ZPLJET_BASE_URL")  # optional — defaults to production

ZPL = "^XA^FO50,50^A0N,50,50^FDZPLJet e2e^FS^XZ"

pytestmark = pytest.mark.skipif(not API_KEY, reason="ZPLJET_API_KEY not set")


def make_client() -> ZplJet:
    assert API_KEY is not None
    return ZplJet(API_KEY, **({"base_url": BASE_URL} if BASE_URL else {}))  # type: ignore[arg-type]


def test_converts_zpl_to_pdf() -> None:
    label = make_client().convert(zpl=ZPL)

    assert label.content_type == "application/pdf"
    assert label.id
    assert label.data[:4] == b"%PDF"


def test_converts_zpl_to_png() -> None:
    label = make_client().convert(zpl=ZPL, format="png", dpmm=12)

    assert label.content_type == "image/png"
    assert label.data[:4] == b"\x89PNG"


def test_rejects_invalid_zpl() -> None:
    with pytest.raises(BadRequestError) as info:
        make_client().convert(zpl="not zpl at all")
    assert info.value.param == "zpl"


def test_rejects_bad_api_key() -> None:
    impostor = ZplJet(
        "zpl_definitely_not_a_real_key",
        **({"base_url": BASE_URL} if BASE_URL else {}),  # type: ignore[arg-type]
    )
    with pytest.raises(AuthenticationError):
        impostor.convert(zpl=ZPL)


def test_hosts_file_or_cleanly_refuses_on_free_plan() -> None:
    try:
        hosted = make_client().convert(zpl=ZPL, output="url")
    except PermissionDeniedError:
        # Free-plan keys can't host — the typed refusal is the correct behavior.
        return
    assert hosted.url.startswith(("http://", "https://"))
    assert hosted.pages >= 1
    expires = datetime.fromisoformat(hosted.expires_at.replace("Z", "+00:00"))
    assert expires > datetime.now(timezone.utc)


async def test_async_client_converts_to_pdf() -> None:
    assert API_KEY is not None
    client = AsyncZplJet(API_KEY, **({"base_url": BASE_URL} if BASE_URL else {}))  # type: ignore[arg-type]
    label = await client.convert(zpl=ZPL)
    assert label.data[:4] == b"%PDF"
