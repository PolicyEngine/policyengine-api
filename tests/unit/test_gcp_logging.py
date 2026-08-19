from unittest.mock import Mock

from policyengine_api.gcp_logging import _LazyGoogleLogger


def test_local_logging_uses_stderr_without_initializing_google(monkeypatch):
    monkeypatch.delenv("GAE_ENV", raising=False)
    monkeypatch.delenv("K_SERVICE", raising=False)
    logger = _LazyGoogleLogger("test-local")
    logger._fallback_logger = Mock()
    payload = {"message": "cache miss"}

    logger.log_struct(payload, severity="WARNING", labels={"cache": "analysis"})

    assert logger._initialization_failed is True
    assert logger._google_logger is None
    logger._fallback_logger.log.assert_called_once_with(30, "%s", payload)


def test_remote_logging_failure_falls_back_and_disables_retries(monkeypatch):
    monkeypatch.setenv("K_SERVICE", "policyengine-api")
    remote_logger = Mock()
    remote_logger.log_struct.side_effect = ConnectionError("logging unavailable")
    logger = _LazyGoogleLogger("test-deployed")
    logger._google_logger = remote_logger
    logger._fallback_logger = Mock()
    payload = {"message": "cache write"}

    logger.log_struct(payload, severity="INFO", labels={"cache": "household"})
    logger.log_struct(payload, severity="INFO", labels={"cache": "household"})

    remote_logger.log_struct.assert_called_once_with(
        payload,
        severity="INFO",
        labels={"cache": "household"},
    )
    assert logger._initialization_failed is True
    assert logger._google_logger is None
    assert logger._fallback_logger.log.call_count == 2
