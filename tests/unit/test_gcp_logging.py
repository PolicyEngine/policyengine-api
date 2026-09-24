from unittest.mock import Mock

from policyengine_api import gcp_logging
from policyengine_api.gcp_logging import _RuntimeLogger


def test_runtime_logger_flattens_migration_context_and_omits_response_text(
    monkeypatch,
):
    runtime = Mock()
    monkeypatch.setattr(gcp_logging, "get_runtime", lambda: runtime)
    logger = _RuntimeLogger()

    logger.log_struct(
        {
            "message": "API request served",
            "request_id": "request-1",
            "response_text": "must not be recorded",
            "migration": {
                "route_impl": "flask_fallback",
                "db_read_source": "cloud_sql",
            },
        },
        severity="WARNING",
        labels={"backend": "simulation_entry"},
    )

    runtime.log.assert_called_once_with(
        "API request served",
        severity="WARNING",
        attributes={
            "request_id": "request-1",
            "route_impl": "flask_fallback",
            "db_read_source": "cloud_sql",
            "backend": "simulation_entry",
        },
    )


def test_runtime_logging_failure_does_not_escape(monkeypatch):
    runtime = Mock()
    runtime.log.side_effect = RuntimeError("logging unavailable")
    monkeypatch.setattr(gcp_logging, "get_runtime", lambda: runtime)

    _RuntimeLogger().log_struct({"message": "operation succeeded"}, severity="INFO")

    runtime.log.assert_called_once()
