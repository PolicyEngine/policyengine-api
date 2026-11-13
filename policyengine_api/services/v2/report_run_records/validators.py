"""Errors of the report-run record service."""

from __future__ import annotations


class ReportRunRecordStorageError(RuntimeError):
    """The detailed-save database could not be read or written for a record."""
