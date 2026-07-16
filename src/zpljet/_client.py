"""ZPLJet API client — sync (:class:`ZplJet`) and async (:class:`AsyncZplJet`)."""

from __future__ import annotations

import asyncio
import email.utils
import http.client
import json
import random
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable, Literal, overload

from ._errors import APIConnectionError, APIError, APITimeoutError, ZplJetError
from ._types import HostedLabel, LabelData
from ._version import __version__

__all__ = ["AsyncZplJet", "Transport", "TransportResponse", "ZplJet"]

DEFAULT_BASE_URL = "https://api.zpljet.com"
DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_RETRIES = 2
MAX_RETRIES_CAP = 10

#: Never sleep longer than this between retries, whatever the server asks.
_MAX_RETRY_DELAY = 30.0
#: Base delay for exponential backoff when the server gives no Retry-After.
_BASE_RETRY_DELAY = 0.5

#: Hosts allowed to use plaintext http without opting in.
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})


def _normalize_max_retries(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("max_retries must be a finite integer >= 0")
    return min(value, MAX_RETRIES_CAP)


def _assert_secure_base_url(base_url: str, allow_insecure_http: bool) -> None:
    """Refuse to send the API key over plaintext http to a non-loopback host."""
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme == "https":
        return
    if parsed.scheme == "http":
        host = (parsed.hostname or "").lower()
        if allow_insecure_http or host in _LOOPBACK_HOSTS:
            return
        raise ZplJetError(
            f"Refusing to send your API key over plaintext http:// to {parsed.netloc}. "
            "Use https, or pass allow_insecure_http=True for local/testing."
        )
    raise ZplJetError(f"Unsupported base_url scheme: {parsed.scheme or '(none)'}")


@dataclass(frozen=True)
class TransportResponse:
    """A raw HTTP response, as returned by a :data:`Transport`."""

    status: int
    headers: Mapping[str, str]
    body: bytes

    def header(self, name: str) -> str | None:
        """Case-insensitive header lookup."""
        lowered = name.lower()
        for key, value in self.headers.items():
            if key.lower() == lowered:
                return value
        return None


#: Sends one POST request: ``(url, body, headers, timeout) -> TransportResponse``.
#: Must raise :class:`APITimeoutError` / :class:`APIConnectionError` on
#: transport failures. Inject a custom one for proxies or tests.
Transport = Callable[[str, bytes, Mapping[str, str], float], TransportResponse]


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(  # type: ignore[override]
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: Mapping[str, str],
        newurl: str,
    ) -> None:
        return None


_NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirectHandler())


def _urllib_transport(
    url: str, body: bytes, headers: Mapping[str, str], timeout: float
) -> TransportResponse:
    """Default transport — stdlib only, no dependencies.

    Note: ``urllib`` opens a fresh connection per request (no keep-alive).
    That is fine for typical label volumes; for sustained high throughput,
    inject a pooling :data:`Transport` built on your HTTP stack of choice.
    """
    request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
    try:
        with _NO_REDIRECT_OPENER.open(request, timeout=timeout) as response:
            return TransportResponse(
                status=response.status,
                headers=dict(response.headers.items()),
                body=response.read(),
            )
    except urllib.error.HTTPError as exc:
        # Non-2xx responses arrive here — they are responses, not failures.
        # Reading the body can still fail mid-stream, though, and exceptions
        # raised inside this handler skip the sibling clauses below.
        with exc:
            try:
                error_body = exc.read()
            except (http.client.HTTPException, OSError) as read_exc:
                raise APIConnectionError(
                    f"Request to {url} failed while reading the response: {read_exc}"
                ) from read_exc
            return TransportResponse(
                status=exc.code,
                headers=dict(exc.headers.items()) if exc.headers else {},
                body=error_body,
            )
    except socket.timeout as exc:
        raise APITimeoutError(f"Request to {url} timed out after {timeout}s") from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, socket.timeout):
            raise APITimeoutError(f"Request to {url} timed out after {timeout}s") from exc
        raise APIConnectionError(f"Request to {url} failed: {exc.reason}") from exc
    except http.client.HTTPException as exc:
        # e.g. IncompleteRead when the connection drops mid-body — an
        # HTTPException, NOT an OSError, so it needs its own clause to keep
        # the "raises APIConnectionError" contract (and stay retryable).
        raise APIConnectionError(f"Request to {url} failed: {exc!r}") from exc
    except OSError as exc:
        raise APIConnectionError(f"Request to {url} failed: {exc}") from exc


class ZplJet:
    """ZPLJet API client.

    ::

        from zpljet import ZplJet

        zpljet = ZplJet(api_key=os.environ["ZPLJET_API_KEY"])
        label = zpljet.convert(zpl="^XA^FO50,50^A0N,50,50^FDHello^FS^XZ")
        Path("label.pdf").write_bytes(label.data)

    Requests that fail with a rate limit (429), a transient server error, or
    a network error are retried automatically with exponential backoff
    (honoring ``Retry-After``). Configure via ``max_retries`` and
    ``timeout``, or per call.

    :param api_key: Your ZPLJet API key (``zpl_…``), created in the dashboard
        at https://zpljet.com/dashboard. Keep it server-side.
    :param base_url: API origin. Defaults to ``https://api.zpljet.com``.
    :param timeout: Per-attempt timeout in seconds. Defaults to ``60``.
    :param max_retries: How many times a failed request is automatically
        retried. Defaults to ``2``. Set ``0`` to disable.
    :param transport: Custom :data:`Transport` — useful for proxies,
        instrumentation, and tests. Defaults to a stdlib ``urllib`` transport.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        allow_insecure_http: bool = False,
        transport: Transport | None = None,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ZplJetError(
                "Missing API key. Pass ZplJet(api_key='zpl_…') — create one at "
                "https://zpljet.com/dashboard."
            )
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        _assert_secure_base_url(self.base_url, allow_insecure_http)
        self.timeout = timeout
        self.max_retries = _normalize_max_retries(max_retries)
        self._transport: Transport = transport or _urllib_transport

    @overload
    def convert(
        self,
        zpl: str,
        *,
        dpmm: int | None = ...,
        width_mm: float | None = ...,
        height_mm: float | None = ...,
        format: Literal["pdf", "png"] | None = ...,
        output: Literal["url"],
        timeout: float | None = ...,
        max_retries: int | None = ...,
    ) -> HostedLabel: ...

    @overload
    def convert(
        self,
        zpl: str,
        *,
        dpmm: int | None = ...,
        width_mm: float | None = ...,
        height_mm: float | None = ...,
        format: Literal["pdf", "png"] | None = ...,
        output: Literal["data", None] = ...,
        timeout: float | None = ...,
        max_retries: int | None = ...,
    ) -> LabelData: ...

    def convert(
        self,
        zpl: str,
        *,
        dpmm: int | None = None,
        width_mm: float | None = None,
        height_mm: float | None = None,
        format: Literal["pdf", "png"] | None = None,
        output: Literal["data", "url"] | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
    ) -> LabelData | HostedLabel:
        """Convert ZPL to a PDF or PNG.

        With ``output="data"`` (the default) the API returns the raw file
        bytes and stores nothing. With ``output="url"`` (paid plans) the file
        is hosted and a public link is returned.

        :param zpl: Raw ZPL — one or more ``^XA…^XZ`` label blocks. Max 512 KB.
        :param dpmm: Print density in dots/mm: 6, 8 (default, 203 dpi),
            12 (300 dpi), or 24 (600 dpi).
        :param width_mm: Physical label width in millimeters (default 101.6).
        :param height_mm: Physical label height in millimeters (default 152.4).
        :param format: ``"pdf"`` (default) or ``"png"``.
        :param output: ``"data"`` (default) or ``"url"`` (paid plans).
        :param timeout: Per-attempt timeout override for this call, seconds.
        :param max_retries: Retry-count override for this call.

        :raises BadRequestError: the ZPL or parameters failed validation (400)
        :raises AuthenticationError: missing or invalid API key (401)
        :raises QuotaExceededError: monthly quota used up (402)
        :raises PermissionDeniedError: hosting not allowed for this account (403)
        :raises RateLimitError: rate limit exceeded, after retries (429)
        :raises ConversionFailedError: the engine could not render the ZPL (502)
        :raises APIConnectionError: network failure or timeout, after retries
        """
        body: dict[str, Any] = {"zpl": zpl}
        if dpmm is not None:
            body["dpmm"] = dpmm
        if width_mm is not None:
            body["widthMm"] = width_mm
        if height_mm is not None:
            body["heightMm"] = height_mm
        if format is not None:
            body["format"] = format
        if output is not None:
            body["output"] = output

        response = self._request_with_retries("/v1/convert", body, timeout, max_retries)

        if output == "url":
            return _parse_hosted_label(response.body)
        return LabelData(
            data=response.body,
            content_type=response.header("content-type") or "application/octet-stream",
            id=response.header("x-conversion-id") or "",
        )

    def _request_with_retries(
        self,
        path: str,
        body: dict[str, Any],
        timeout: float | None,
        max_retries: int | None,
    ) -> TransportResponse:
        """POST ``body`` as JSON, retrying transient failures."""
        url = f"{self.base_url}{path}"
        payload = json.dumps(body).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": self.api_key,
            "User-Agent": f"zpljet-python/{__version__}",
        }
        retries = (
            self.max_retries
            if max_retries is None
            else _normalize_max_retries(max_retries)
        )
        attempt_timeout = self.timeout if timeout is None else timeout

        attempt = 0
        while True:
            error: APIError | APIConnectionError
            header_retry_after: float | None = None
            try:
                response = self._transport(url, payload, headers, attempt_timeout)
                if 200 <= response.status < 300:
                    return response
                error = APIError.from_response(response.status, _parse_error_body(response.body))
                header_retry_after = _parse_retry_after_header(response.header("retry-after"))
            except APIConnectionError as exc:
                error = exc

            if attempt >= retries or not _is_retryable(error):
                raise error
            _sleep(_retry_delay(error, attempt, header_retry_after))
            attempt += 1


class AsyncZplJet:
    """Async variant of :class:`ZplJet` with the same interface.

    The API is a single short-lived POST, so this wraps the (dependency-free)
    sync client in :func:`asyncio.to_thread` rather than pulling in an async
    HTTP library — same reliability behavior, zero dependencies. Each call
    runs on the default executor and never blocks the event loop.

    One consequence: retry backoff waits happen on that executor thread, so a
    rate-limit storm can park several worker threads at once. If your app
    shares the default executor with other heavy ``to_thread`` work, cap
    concurrency with a semaphore (see ``examples/05_async_batch.py``) or set
    ``max_retries=0`` and retry at the call site.

    ::

        zpljet = AsyncZplJet(api_key=os.environ["ZPLJET_API_KEY"])
        label = await zpljet.convert(zpl="^XA…^XZ")
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        allow_insecure_http: bool = False,
        transport: Transport | None = None,
    ) -> None:
        self._client = ZplJet(
            api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            allow_insecure_http=allow_insecure_http,
            transport=transport,
        )

    @property
    def base_url(self) -> str:
        return self._client.base_url

    @overload
    async def convert(
        self,
        zpl: str,
        *,
        dpmm: int | None = ...,
        width_mm: float | None = ...,
        height_mm: float | None = ...,
        format: Literal["pdf", "png"] | None = ...,
        output: Literal["url"],
        timeout: float | None = ...,
        max_retries: int | None = ...,
    ) -> HostedLabel: ...

    @overload
    async def convert(
        self,
        zpl: str,
        *,
        dpmm: int | None = ...,
        width_mm: float | None = ...,
        height_mm: float | None = ...,
        format: Literal["pdf", "png"] | None = ...,
        output: Literal["data", None] = ...,
        timeout: float | None = ...,
        max_retries: int | None = ...,
    ) -> LabelData: ...

    async def convert(
        self,
        zpl: str,
        *,
        dpmm: int | None = None,
        width_mm: float | None = None,
        height_mm: float | None = None,
        format: Literal["pdf", "png"] | None = None,
        output: Literal["data", "url"] | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
    ) -> LabelData | HostedLabel:
        """Async :meth:`ZplJet.convert` — same parameters and errors."""
        return await asyncio.to_thread(
            self._client.convert,  # type: ignore[arg-type]
            zpl,
            dpmm=dpmm,
            width_mm=width_mm,
            height_mm=height_mm,
            format=format,
            output=output,
            timeout=timeout,
            max_retries=max_retries,
        )


def _parse_error_body(body: bytes) -> dict[str, Any]:
    """Parse the structured ``{"error": {…}}`` body; tolerate anything else."""
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    if isinstance(parsed, dict) and isinstance(parsed.get("error"), dict):
        return parsed["error"]  # type: ignore[no-any-return]
    return {}


def _parse_success_object(body: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ZplJetError("Invalid JSON in successful API response") from exc
    if not isinstance(parsed, dict):
        raise ZplJetError("Invalid payload in successful API response")
    return parsed


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ZplJetError(f"Invalid {key} in successful API response")
    return value


def _parse_hosted_label(body: bytes) -> HostedLabel:
    payload = _parse_success_object(body)
    pages = payload.get("pages")
    retention_days = payload.get("retentionDays")
    if not isinstance(pages, int) or isinstance(pages, bool) or pages < 1:
        raise ZplJetError("Invalid pages in successful API response")
    if (
        not isinstance(retention_days, int)
        or isinstance(retention_days, bool)
        or retention_days < 1
    ):
        raise ZplJetError("Invalid retentionDays in successful API response")
    return HostedLabel(
        id=_required_string(payload, "id"),
        url=_required_string(payload, "url"),
        pages=pages,
        retention_days=retention_days,
        expires_at=_required_string(payload, "expiresAt"),
    )


def _is_retryable(error: APIError | APIConnectionError) -> bool:
    """Whether an error is worth retrying: network failures, timeouts, rate
    limits, and transient 5xx. ``conversion_failed`` (502) is excluded — it
    means the engine rejected the ZPL itself, so a retry would fail
    identically."""
    if isinstance(error, APIConnectionError):
        return True
    if error.status == 429:
        return True
    return error.status >= 500 and error.code != "conversion_failed"


def _parse_retry_after_header(value: str | None) -> float | None:
    """The ``Retry-After`` response header in seconds — delta-seconds or an
    HTTP-date. Used when the body carries no ``retryAfter`` field (e.g. a
    gateway 429/503 with an HTML body)."""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, when.timestamp() - time.time())


def _retry_delay(
    error: APIError | APIConnectionError,
    attempt: int,
    header_retry_after: float | None = None,
) -> float:
    """Delay before the next retry — the body's ``retryAfter``, else the
    ``Retry-After`` header, else exponential backoff with jitter."""
    if isinstance(error, APIError):
        retry_after = error.raw.get("retryAfter")
        if isinstance(retry_after, (int, float)) and not isinstance(retry_after, bool):
            return min(float(retry_after), _MAX_RETRY_DELAY)
    if header_retry_after is not None:
        return min(header_retry_after, _MAX_RETRY_DELAY)
    backoff = _BASE_RETRY_DELAY * (2.0**attempt)
    return min(backoff + backoff * 0.25 * random.random(), _MAX_RETRY_DELAY)


def _sleep(seconds: float) -> None:
    """Module-level indirection so tests can stub the wait out."""
    if seconds > 0:
        time.sleep(seconds)
