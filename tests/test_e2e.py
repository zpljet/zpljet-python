"""Live API tests gated by ZPLJET_API_KEY."""

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
BASE_URL = os.environ.get("ZPLJET_BASE_URL")

ZPL = "^XA^FO50,50^A0N,50,50^FDZPLJet e2e^FS^XZ"

pytestmark = pytest.mark.skipif(not API_KEY, reason="ZPLJET_API_KEY not set")


def make_client() -> ZplJet:
    assert API_KEY is not None
    return ZplJet(API_KEY, base_url=BASE_URL) if BASE_URL else ZplJet(API_KEY)


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
    impostor = (
        ZplJet("zpl_definitely_not_a_real_key", base_url=BASE_URL)
        if BASE_URL
        else ZplJet("zpl_definitely_not_a_real_key")
    )
    with pytest.raises(AuthenticationError):
        impostor.convert(zpl=ZPL)


def test_hosts_file_or_cleanly_refuses_on_free_plan() -> None:
    try:
        hosted = make_client().convert(zpl=ZPL, output="url")
    except PermissionDeniedError:
        return
    assert hosted.url.startswith(("http://", "https://"))
    assert hosted.pages >= 1
    expires = datetime.fromisoformat(hosted.expires_at.replace("Z", "+00:00"))
    assert expires > datetime.now(timezone.utc)


async def test_async_client_converts_to_pdf() -> None:
    assert API_KEY is not None
    client = AsyncZplJet(API_KEY, base_url=BASE_URL) if BASE_URL else AsyncZplJet(API_KEY)
    label = await client.convert(zpl=ZPL)
    assert label.data[:4] == b"%PDF"
