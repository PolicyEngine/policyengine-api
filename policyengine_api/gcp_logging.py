import logging
from typing import Optional


class _LazyGoogleLogger:
    """Lazily initialize Google Cloud Logging and fall back to stderr."""

    def __init__(self, logger_name: str):
        self._logger_name = logger_name
        self._google_logger = None
        self._initialization_failed = False
        self._fallback_logger = logging.getLogger(logger_name)

    def _get_google_logger(self):
        if self._google_logger is not None:
            return self._google_logger
        if self._initialization_failed:
            return None
        try:
            from google.cloud.logging import Client

            self._google_logger = Client().logger(self._logger_name)
            return self._google_logger
        except Exception:
            self._initialization_failed = True
            return None

    def log_struct(
        self,
        info: dict,
        severity: str = "INFO",
        *,
        labels: Optional[dict] = None,
    ) -> None:
        google_logger = self._get_google_logger()
        if google_logger is not None:
            google_logger.log_struct(info, severity=severity, labels=labels)
            return

        level = getattr(logging, severity.upper(), logging.INFO)
        self._fallback_logger.log(level, "%s", info)


logger = _LazyGoogleLogger("policyengine-api")
