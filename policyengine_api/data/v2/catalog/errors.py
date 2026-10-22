"""The error raised when catalog sources cannot be normalized."""

from __future__ import annotations


class CatalogExtractionError(RuntimeError):
    """Raised before database access when source metadata cannot be normalized."""
