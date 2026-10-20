import re

from policyengine_observability import (
    GoogleCloudLogFormatter,
    StdoutLogDestination,
)

from policyengine_api.observability import (
    _build_runtime,
    record_unhandled_exception,
    runtime,
    set_runtime_context,
)


def _fail_observability(*_arguments, **_options):
    message = "observability unavailable"
    raise RuntimeError(message)


def test_runtime_uses_consumer_owned_identity_and_stdout(monkeypatch):
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    monkeypatch.setenv("OTEL_TRACES_SAMPLER_ARG", "0.01")
    monkeypatch.setenv("OBSERVABILITY_SERVICE_NAMESPACE", "example.stack")
    monkeypatch.setenv("OBSERVABILITY_TRACE_PROJECT_ID", "trace-project")
    monkeypatch.setenv("K_REVISION", "policyengine-api-00123-test")

    runtime = _build_runtime()
    try:
        assert runtime.config.service.namespace == "example.stack"
        assert runtime.config.otel.sampling_ratio == 1.0
        assert runtime.config.application_attribute_keys is None
        assert runtime.config.dispatch_attribute_keys == frozenset({"observability_id"})
        assert re.fullmatch(
            r"policyengine-api-00123-test:\d+:[0-9a-f]{32}",
            runtime.config.deployment.instance_id or "",
        )
        assert len(runtime.config.logging.destinations) == 1
        destination = runtime.config.logging.destinations[0]
        assert isinstance(destination, StdoutLogDestination)
        assert isinstance(destination.formatter, GoogleCloudLogFormatter)
        assert destination.formatter.project_id == "trace-project"
    finally:
        runtime.shutdown()


def test_runtime_context_failure_does_not_escape(monkeypatch):
    monkeypatch.setattr(
        runtime,
        "set_context",
        lambda **_attributes: (_ for _ in ()).throw(
            RuntimeError("observability unavailable")
        ),
    )

    set_runtime_context(country_id="us")


def test_unhandled_exception_is_recorded_as_unhandled_server_error(monkeypatch):
    recorded_calls = []
    monkeypatch.setattr(
        runtime,
        "record_exception",
        lambda error, **options: recorded_calls.append((error, options)),
    )
    error = RuntimeError("engine exploded")

    record_unhandled_exception(error)

    assert recorded_calls == [(error, {"handled": False, "status_code": 500})]


def test_unhandled_exception_recording_failure_does_not_escape(monkeypatch):
    monkeypatch.setattr(runtime, "record_exception", _fail_observability)

    record_unhandled_exception(RuntimeError("engine exploded"))
