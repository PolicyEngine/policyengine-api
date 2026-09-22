from policyengine_observability import (
    GoogleCloudLogFormatter,
    StdoutLogDestination,
)

from policyengine_api.observability import _build_runtime


def test_runtime_uses_consumer_owned_identity_and_stdout(monkeypatch):
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    monkeypatch.setenv("OBSERVABILITY_SERVICE_NAMESPACE", "example.stack")
    monkeypatch.setenv("OBSERVABILITY_TRACE_PROJECT_ID", "trace-project")

    runtime = _build_runtime()
    try:
        assert runtime.config.service.namespace == "example.stack"
        assert len(runtime.config.logging.destinations) == 1
        destination = runtime.config.logging.destinations[0]
        assert isinstance(destination, StdoutLogDestination)
        assert isinstance(destination.formatter, GoogleCloudLogFormatter)
        assert destination.formatter.project_id == "trace-project"
    finally:
        runtime.shutdown()
