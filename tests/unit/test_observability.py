from datetime import UTC, datetime, timedelta

import pytest

from policyengine_api.observability import (
    build_lifecycle_event,
    build_metric_attributes,
    build_traceparent,
    duration_since_requested_at,
    parse_bool,
    parse_header_value_pairs,
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
        "geography_type": "state",
        "geography_code": "tx",
        "capture_mode": "disabled",
        "country_package_version": "1.632.5",
        "policyengine_version": "0.13.0",
        "modal_app_name": "policyengine-simulation-us1-632-5-uk2-78-0",
        "service": "policyengine-api",
        "status": "submitted",
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
