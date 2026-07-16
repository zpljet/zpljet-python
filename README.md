# zpljet

Official Python SDK for the [ZPLJet](https://zpljet.com) API — fast ZPL → PDF/PNG conversion.

[![PyPI version](https://img.shields.io/pypi/v/zpljet.svg)](https://pypi.org/project/zpljet/)
[![CI](https://github.com/zpljet/zpljet-python/actions/workflows/ci.yml/badge.svg)](https://github.com/zpljet/zpljet-python/actions/workflows/ci.yml)
[![license](https://img.shields.io/pypi/l/zpljet.svg)](./LICENSE)

- **Zero dependencies** — a single small client on top of the stdlib
- **Fully typed** (`py.typed`) — parameters, results, and every API error code
- **Reliable by default** — automatic retries with exponential backoff (honoring `Retry-After`), per-request timeouts, typed exceptions
- **Sync and async** — `ZplJet` for scripts and servers, `AsyncZplJet` for asyncio code
- Python ≥ 3.9

## Installation

```sh
pip install zpljet
# or: uv add zpljet / poetry add zpljet
```

## Quickstart

Create an API key in the [dashboard](https://zpljet.com/dashboard) (keys look like `zpl_…`), then:

```python
import os
from pathlib import Path

from zpljet import ZplJet

zpljet = ZplJet(api_key=os.environ["ZPLJET_API_KEY"])

label = zpljet.convert(zpl="^XA^FO50,50^A0N,50,50^FDHello^FS^XZ")

# label.data is the raw PDF bytes — nothing is stored server-side.
Path("label.pdf").write_bytes(label.data)
```

> **Keep your API key server-side.** Anyone with the key can spend your quota.

## Usage

### Convert to PDF or PNG

`convert()` accepts every parameter of [`POST /v1/convert`](https://zpljet.com/docs/api-reference):

```python
label = zpljet.convert(
    zpl="^XA^FO50,50^A0N,50,50^FDHello^FS^XZ",
    format="png",     # "pdf" (default) | "png"
    dpmm=12,          # 6 | 8 (default, 203 dpi) | 12 (300 dpi) | 24 (600 dpi)
    width_mm=101.6,   # label width, default 4 in
    height_mm=152.4,  # label height, default 6 in
)

label.data          # bytes — the file
label.content_type  # "application/pdf" | "image/png"
label.id            # conversion id (shows up in your dashboard)
```

### Hosted URLs (paid plans)

Pass `output="url"` to have ZPLJet host the file and return a public link
instead of the bytes. Files are retained for your account's retention window
(a dashboard setting, up to your plan's maximum).

```python
hosted = zpljet.convert(zpl="^XA^FO50,50^A0N,50,50^FDHello^FS^XZ", output="url")

hosted.url             # public URL to the PDF (works until the file is deleted)
hosted.pages           # pages rendered (one per ^XA…^XZ block)
hosted.retention_days  # how long the file is kept
hosted.expires_at      # when the file is deleted and the URL stops working (ISO 8601, UTC)
```

The return type narrows automatically: `output="url"` gives a `HostedLabel`,
everything else a `LabelData`.

### Async

`AsyncZplJet` has the identical interface for asyncio code:

```python
from zpljet import AsyncZplJet

zpljet = AsyncZplJet(api_key=os.environ["ZPLJET_API_KEY"])
label = await zpljet.convert(zpl="^XA^FO50,50^A0N,50,50^FDHello^FS^XZ")
```

(The API is a single short-lived POST, so calls are offloaded to a thread
instead of pulling in an async HTTP dependency — the event loop is never
blocked. Retry waits happen on that worker thread, so bound your concurrency
with a semaphore for large batches, as in
[`examples/05_async_batch.py`](./examples/05_async_batch.py).)

### Error handling

Every API error code maps to a dedicated exception, so you branch with
`except` — no string matching:

```python
from zpljet import (
    ZplJet,
    APIConnectionError,
    BadRequestError,
    ConversionFailedError,
    QuotaExceededError,
    RateLimitError,
)

try:
    label = zpljet.convert(zpl=zpl)
except BadRequestError as err:
    print(f"Invalid request ({err.param}): {err.message}")
except QuotaExceededError as err:
    print(f"Quota used up ({err.used}/{err.quota}), resets {err.resets_at}")
except RateLimitError as err:
    print(f"Rate limited — retry after {err.retry_after}s")  # already auto-retried
except ConversionFailedError as err:
    print(f"Engine rejected the ZPL (conversion {err.conversion_id})")
except APIConnectionError as err:
    print(f"Network problem: {err}")  # already auto-retried
```

| Exception | Status | `error.code` | Extra fields |
| --- | --- | --- | --- |
| `BadRequestError` | 400 | `invalid_request` | `param` |
| `AuthenticationError` | 401 | `missing_api_key` · `invalid_api_key` | — |
| `QuotaExceededError` | 402 | `quota_exceeded` | `plan`, `quota`, `used`, `resets_at` |
| `PermissionDeniedError` | 403 | `hosting_not_allowed` · `no_retention_enforced` | — |
| `PayloadTooLargeError` | 413 | `payload_too_large` | — |
| `RateLimitError` | 429 | `rate_limit_exceeded` | `retry_after`, `retry_at` |
| `ConversionFailedError` | 502 | `conversion_failed` | `conversion_id` |
| `ServiceUnavailableError` | 503 | `service_unavailable` | `retry_after` |
| `APIError` | any | anything else | `status`, `code`, `raw` |
| `APITimeoutError` | — | (an attempt timed out) | — |
| `APIConnectionError` | — | (request never got a response) | — |

All of these extend `ZplJetError`, and every HTTP error carries `status`,
`code`, `doc_url`, and the raw error payload in `raw`. Full code reference:
[zpljet.com/docs/errors](https://zpljet.com/docs/errors).

### Retries

Rate limits (429), transient server errors (5xx), timeouts, and network
failures are retried automatically — up to 2 times by default, with
exponential backoff, honoring the server's `Retry-After`. A 503
`service_unavailable` means the render engine is temporarily unavailable; the
request was not charged against quota. A 502
`conversion_failed` is **not** retried: it means the engine rejected the ZPL
itself, so a retry would fail identically.

```python
# Client-wide
zpljet = ZplJet(api_key=key, max_retries=5)

# Or per request
zpljet.convert(zpl=zpl, max_retries=0)  # fail fast
```

### Timeouts

Each attempt has a 60-second timeout by default:

```python
zpljet = ZplJet(api_key=key, timeout=10.0)

# Per request:
zpljet.convert(zpl=zpl, timeout=5.0)
```

A timed-out attempt raises `APITimeoutError` (after retries).

### Configuration

```python
zpljet = ZplJet(
    api_key="zpl_…",                     # required
    base_url="https://api.zpljet.com",   # default
    timeout=60.0,                        # per-attempt timeout, seconds
    max_retries=2,                       # automatic retries
    transport=my_transport,              # custom transport (proxies, tests)
)
```

The default transport is stdlib `urllib` — zero dependencies, but a fresh
connection per request. For sustained high throughput, inject a pooling
`Transport` built on your HTTP stack of choice (any callable
`(url, body, headers, timeout) -> TransportResponse` works).

## Examples

Runnable scripts live in [`examples/`](./examples):

```sh
ZPLJET_API_KEY=zpl_… python examples/01_convert_to_pdf.py
```

## Contributing & development

```sh
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

ruff check .          # lint
mypy                  # strict type check
pytest                # unit tests (no network)

# End-to-end tests against the live API (uses your quota):
ZPLJET_API_KEY=zpl_… pytest tests/test_e2e.py
```

## License

[MIT](./LICENSE)
