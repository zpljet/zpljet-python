"""Result types for the ZPLJet API.

These mirror the ``POST /v1/convert`` contract exactly — see
https://zpljet.com/docs/api-reference for the canonical reference.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["HostedLabel", "LabelData"]


@dataclass(frozen=True)
class LabelData:
    """Result of a conversion with ``output="data"`` (the default)."""

    data: bytes
    """The rendered file bytes (PDF or PNG)."""

    content_type: str
    """``"application/pdf"`` or ``"image/png"``."""

    id: str
    """Conversion id (from the ``X-Conversion-Id`` response header)."""


@dataclass(frozen=True)
class HostedLabel:
    """Result of a conversion with ``output="url"`` (hosted, paid plans)."""

    id: str
    """Conversion id."""

    url: str
    """Public URL to the hosted file. Works until the file is deleted at
    ``expires_at``."""

    pages: int
    """Number of pages rendered (one per ``^XA…^XZ`` block)."""

    retention_days: int
    """How many days the file is retained."""

    expires_at: str
    """ISO 8601 UTC timestamp — when the hosted file is deleted and its URL
    stops working."""
