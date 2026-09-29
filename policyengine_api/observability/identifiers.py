"""Diagnostic correlation identifiers for API requests and report work."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

OBSERVABILITY_ID_HEADER = "X-PolicyEngine-Observability-Id"


def generate_observability_id() -> str:
    """Create an identifier used only to correlate observability records."""

    return str(uuid4())


def normalize_observability_id(value: Any) -> str | None:
    """Return a canonical UUID string, or ``None`` for malformed input."""

    if not isinstance(value, str):
        return None
    try:
        return str(UUID(value))
    except (ValueError, AttributeError):
        return None
