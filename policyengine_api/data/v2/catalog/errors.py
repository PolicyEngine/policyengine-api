"""Errors raised while catalog sources are read and normalized."""

from __future__ import annotations


class CatalogExtractionError(RuntimeError):
    """Raised before database access when source metadata cannot be normalized."""


class CertifiedDataReadError(RuntimeError):
    """Raised when a certified artifact does not have the structure expected.

    Its message names only HDF5 entries and counts, so it is safe to print.
    """
