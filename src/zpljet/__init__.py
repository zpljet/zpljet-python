"""Official Python SDK for the ZPLJet API — fast ZPL → PDF/PNG conversion.

Docs: https://zpljet.com/docs

::

    from zpljet import ZplJet

    zpljet = ZplJet(api_key=os.environ["ZPLJET_API_KEY"])
    label = zpljet.convert(zpl="^XA^FO50,50^A0N,50,50^FDHello^FS^XZ")
    Path("label.pdf").write_bytes(label.data)
"""

from ._client import AsyncZplJet, Transport, TransportResponse, ZplJet
from ._errors import (
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
from ._types import HostedLabel, LabelData
from ._version import __version__

__all__ = [
    "APIConnectionError",
    "APIError",
    "APITimeoutError",
    "AsyncZplJet",
    "AuthenticationError",
    "BadRequestError",
    "ConversionFailedError",
    "HostedLabel",
    "LabelData",
    "PayloadTooLargeError",
    "PermissionDeniedError",
    "QuotaExceededError",
    "RateLimitError",
    "ServiceUnavailableError",
    "Transport",
    "TransportResponse",
    "ZplJet",
    "ZplJetError",
    "__version__",
]
