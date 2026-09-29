"""Compatibility facade for application-owned structured logging.

Existing API modules call ``logger.log_struct``.  The facade keeps that small
surface while sending records through the explicitly owned v2 runtime.  Cloud
Run captures the resulting JSON from standard output, so request threads never
call the Cloud Logging API.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from policyengine_api.observability import get_runtime


class _RuntimeLogger:
    """Adapt the former ``log_struct`` call shape to the v2 runtime."""

    def log_struct(
        self,
        info: Mapping[str, Any],
        severity: str = "INFO",
        *,
        labels: Mapping[str, Any] | None = None,
    ) -> None:
        """Record an allowlisted structured message without affecting callers."""

        try:
            message = str(info.get("message") or "API event")
            attributes = {
                key: value
                for key, value in info.items()
                if key not in {"message", "migration", "response_text"}
            }
            migration = info.get("migration")
            if isinstance(migration, Mapping):
                attributes.update(migration)
            if labels:
                attributes.update(labels)
            get_runtime().log(
                message,
                severity=severity,
                attributes=attributes,
            )
        except Exception:
            pass


logger = _RuntimeLogger()
