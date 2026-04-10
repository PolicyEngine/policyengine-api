from datetime import UTC, datetime, timedelta

import pytest

from policyengine_api.observability import (
    build_lifecycle_event,
    build_metric_attributes,
    build_span_attributes,
    build_traceparent,
    duration_since_requested_at,
    FAILURE_COUNT_METRIC_NAME,
    observe_stage,
    parse_bool,
    parse_header_value_pairs,
    STAGE_DURATION_METRIC_NAME,
)


def test_parse_header_value_pairs__supports_commas_and_newlines():
    assert parse_header_value_pairs("Authorization=Bearer abc,\nX-Scope=ops") == {
        "Authorization": "Bearer abc",
        "X-Scope": "ops",
    }


def test_parse_header_value_pairs__rejects_invalid_entries():
    with pytest.raises(ValueError, match="key=value"):
        parse_header_value_pairs("Authorization")


def test_parse_bool__supports_common_truthy_and_falsey_values():
    assert parse_bool("true") is True
    assert parse_bool("YES") is True
    assert parse_bool("0") is False
    assert parse_bool(None, default=True) is True


def test_build_metric_attributes__keeps_low_cardinality_fields():
    attributes = build_metric_attributes(
        {
            "country": "us",
            "simulation_kind": "state",
            "geography_type": "state",
            "geography_code": "tx",
            "capture_mode": "disabled",
            "country_package_version": "1.632.5",
            "policyengine_version": "0.13.0",
            "modal_app_name": "policyengine-simulation-us1-632-5-uk2-78-0",
            "run_id": "run-123",
        },
        service="policyengine-api",
        status="submitted",
    )

    assert attributes == {
        "country": "us",
        "simulation_kind": "state",
        "capture_mode": "disabled",
        "country_package_version": "1.632.5",
        "policyengine_version": "0.13.0",
        "service": "policyengine-api",
        "status": "submitted",
    }


def test_build_span_attributes__preserves_high_cardinality_trace_context():
    attributes = build_span_attributes(
        {
            "run_id": "run-123",
            "process_id": "proc-123",
            "country": "us",
            "simulation_kind": "state",
            "geography_type": "state",
            "geography_code": "tx",
            "config_hash": "sha256:test",
        },
        service="policyengine-api",
    )

    assert attributes == {
        "run_id": "run-123",
        "process_id": "proc-123",
        "country": "us",
        "simulation_kind": "state",
        "geography_type": "state",
        "geography_code": "tx",
        "config_hash": "sha256:test",
        "service": "policyengine-api",
    }


def test_build_lifecycle_event__includes_telemetry_and_duration():
    payload = build_lifecycle_event(
        stage="job.submitted",
        status="submitted",
        service="policyengine-api",
        telemetry={"run_id": "run-123", "country": "us"},
        duration_seconds=1.5,
        details={"job_id": "fc-123"},
    )

    assert payload["event_name"] == "simulation.lifecycle"
    assert payload["run_id"] == "run-123"
    assert payload["country"] == "us"
    assert payload["duration_seconds"] == 1.5
    assert payload["details"] == {"job_id": "fc-123"}


def test_duration_since_requested_at__returns_elapsed_seconds():
    requested_at = (
        datetime.now(UTC) - timedelta(seconds=5)
    ).isoformat()

    duration = duration_since_requested_at({"requested_at": requested_at})

    assert duration is not None
    assert 0 < duration < 30


def test_build_traceparent__formats_w3c_traceparent():
    class FakeSpanContext:
        is_valid = True
        trace_id = 0x1234
        span_id = 0x5678
        trace_flags = 1

    assert (
        build_traceparent(FakeSpanContext())
        == "00-00000000000000000000000000001234-0000000000005678-01"
    )


class RecordingSpan:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None

    def set_attribute(self, key, value):
        return None

    def add_event(self, name, attributes=None):
        return None


class RecordingObservability:
    def __init__(self):
        self.events = []
        self.histograms = []
        self.counters = []
        self.spans = []

    def emit_lifecycle_event(self, payload):
        self.events.append(payload)

    def emit_counter(self, name, value=1, attributes=None):
        self.counters.append(
            {"name": name, "value": value, "attributes": dict(attributes or {})}
        )

    def emit_histogram(self, name, value, attributes=None):
        self.histograms.append(
            {"name": name, "value": value, "attributes": dict(attributes or {})}
        )

    def span(self, name, attributes=None, parent_traceparent=None):
        self.spans.append(
            {
                "name": name,
                "attributes": dict(attributes or {}),
                "parent_traceparent": parent_traceparent,
            }
        )
        return RecordingSpan()


def test_observe_stage__records_duration_metrics_and_lifecycle_events():
    observability = RecordingObservability()
    ticks = iter((10.0, 12.5))

    with observe_stage(
        observability,
        stage="job.setup",
        service="policyengine-api",
        telemetry={"country": "us", "simulation_kind": "state"},
        timer=lambda: next(ticks),
    ):
        pass

    assert observability.spans[0]["name"] == "job.setup"
    assert observability.histograms == [
        {
            "name": STAGE_DURATION_METRIC_NAME,
            "value": 2.5,
            "attributes": {
                "country": "us",
                "simulation_kind": "state",
                "service": "policyengine-api",
                "stage": "job.setup",
                "status": "ok",
            },
        }
    ]
    assert observability.events[0]["stage"] == "job.setup"
    assert observability.events[0]["duration_seconds"] == 2.5


def test_observe_stage__records_failure_metrics_on_exception():
    observability = RecordingObservability()
    ticks = iter((20.0, 21.25))

    with pytest.raises(RuntimeError, match="boom"):
        with observe_stage(
            observability,
            stage="job.submitted",
            service="policyengine-api-modal-client",
            telemetry={"country": "us", "simulation_kind": "state"},
            record_failure_counter=True,
            timer=lambda: next(ticks),
        ):
            raise RuntimeError("boom")

    assert observability.histograms[0]["attributes"]["status"] == "failed"
    assert observability.counters == [
        {
            "name": FAILURE_COUNT_METRIC_NAME,
            "value": 1,
            "attributes": {
                "country": "us",
                "simulation_kind": "state",
                "service": "policyengine-api-modal-client",
                "stage": "job.submitted",
                "status": "failed",
            },
        }
    ]
    assert observability.events[0]["details"]["error"] == "boom"
