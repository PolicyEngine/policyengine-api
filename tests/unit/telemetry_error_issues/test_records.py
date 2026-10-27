"""Tests for telemetry_error_issues.records: primary records and fingerprints."""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest
from telemetry_error_issues.records import (
    fingerprint,
    fingerprint_key,
    fingerprint_parts,
    primary_records,
)

from tests.unit.telemetry_error_issues.report_support import (
    APPLICATION_FRAMES,
    FINGERPRINT_KEY,
    chained_stack,
    exception_record,
    extract_frames,
    failed_request_record,
    message_record,
)


def _frame_header(module_path: str, function_name: str, line_number: int) -> str:
    """Return one stack frame header as the query extracts it."""
    return f'/app/{module_path}", line {line_number}, in {function_name}'


# One exception's stack before and after a file-length split moved the service
# functions into new modules, and after the split made a private helper public.
FRAMES_BEFORE_SPLIT = (
    _frame_header("policyengine_api/routes/report_routes.py", "create_report", 41),
    _frame_header("policyengine_api/services/report_service.py", "create", 88),
    _frame_header(
        "policyengine_api/services/report_service.py", "_resolve_region", 140
    ),
)
FRAMES_AFTER_SPLIT = (
    _frame_header("policyengine_api/routes/report_routes.py", "create_report", 41),
    _frame_header("policyengine_api/services/report/creation.py", "create", 30),
    _frame_header("policyengine_api/services/report/regions.py", "_resolve_region", 12),
)
FRAMES_AFTER_SPLIT_WITH_PUBLIC_HELPER = (
    _frame_header("policyengine_api/routes/report_routes.py", "create_report", 41),
    _frame_header("policyengine_api/services/report/creation.py", "create", 30),
    _frame_header("policyengine_api/services/report/regions.py", "resolve_region", 12),
)


def test_primary_prefers_the_exception_record_of_a_failed_request() -> None:
    exception = exception_record()
    records = [
        message_record(),
        exception,
        failed_request_record(),
    ]

    assert primary_records(records) == [exception]


def test_primary_falls_back_to_the_message_record() -> None:
    message = message_record()

    primary = primary_records([failed_request_record(), message])

    assert primary == [message]
    assert primary[0].kind == "message"


def test_primary_falls_back_to_the_failed_request_record() -> None:
    failed_request = failed_request_record()

    primary = primary_records([failed_request])

    assert primary == [failed_request]
    assert primary[0].kind == "failed_request"


def test_primary_prefers_an_unhandled_exception_over_a_handled_one() -> None:
    handled = exception_record(error_type="KeyError", error_handled=True)
    unhandled = exception_record(
        timestamp=datetime(2026, 10, 20, 16, 0, 1, tzinfo=UTC),
        error_type="LookupError",
    )

    assert primary_records([handled, unhandled]) == [unhandled]


def test_primary_chooses_the_same_record_of_a_tie_in_either_input_order() -> None:
    # One request logged two unhandled exceptions at the same moment.
    stale_data = exception_record()
    timeout = exception_record(error_type="TimeoutError")
    assert fingerprint(stale_data, FINGERPRINT_KEY) != fingerprint(
        timeout, FINGERPRINT_KEY
    )

    forward = primary_records([stale_data, timeout])
    backward = primary_records([timeout, stale_data])

    assert len(forward) == 1
    assert forward == backward


def test_primary_orders_failures_at_one_moment_the_same_way_in_either_input_order():
    saving = message_record(request_key="request-1")
    loading = message_record(request_key="request-2", message_template="failed to load")
    unidentified = message_record(
        request_key=None, trace_key=None, message_template="no request"
    )

    forward = primary_records([saving, loading, unidentified])
    backward = primary_records([unidentified, loading, saving])

    assert forward == backward


def test_primary_prefers_the_earlier_record_before_breaking_a_tie() -> None:
    later = exception_record(
        timestamp=datetime(2026, 10, 20, 16, 0, 1, tzinfo=UTC),
        error_type="AttributeError",
    )
    earlier = exception_record(error_type="ZeroDivisionError")

    assert primary_records([later, earlier]) == [earlier]


def test_primary_treats_a_request_completed_record_with_error_fields_as_an_exception():
    completed = failed_request_record(
        error_type="StaleDataError", frames=APPLICATION_FRAMES
    )

    assert completed.kind == "exception"
    assert primary_records([completed]) == [completed]


def test_primary_correlates_by_trace_when_the_request_id_is_missing() -> None:
    exception = exception_record(request_key=None)
    message = message_record(request_key=None)

    assert primary_records([message, exception]) == [exception]


def test_primary_records_without_request_or_trace_stand_alone() -> None:
    first = message_record(request_key=None, trace_key=None)
    second = message_record(
        request_key=None,
        trace_key=None,
        timestamp=datetime(2026, 10, 20, 17, 0, tzinfo=UTC),
    )

    assert primary_records([second, first]) == [first, second]


def test_primary_keeps_failures_of_different_services_separate() -> None:
    api_failure = failed_request_record()
    simulation_failure = exception_record(
        service_name="policyengine-simulation-entry",
        frames=(),
    )

    # Both failures happen at the same moment, so they are ordered by their
    # values: the exception's fingerprint inputs sort before the failed
    # request's, whichever order the records arrive in.
    expected = [simulation_failure, api_failure]
    assert primary_records([api_failure, simulation_failure]) == expected
    assert primary_records([simulation_failure, api_failure]) == expected


def test_fingerprint_exception_ignores_lines_path_prefixes_and_routes() -> None:
    moved_frames = tuple(
        frame.replace("/app/", "/srv/checkout/").replace("line 4", "line 9")
        for frame in APPLICATION_FRAMES
    )
    first = exception_record()
    second = exception_record(
        frames=moved_frames,
        route="/<country_id>/economy/<int:policy_id>/over/<int:baseline_policy_id>",
    )

    assert fingerprint(first, FINGERPRINT_KEY) == fingerprint(second, FINGERPRINT_KEY)


def test_fingerprint_exception_is_the_same_after_its_functions_move_modules() -> None:
    before_split = exception_record(frames=FRAMES_BEFORE_SPLIT)
    after_split = exception_record(frames=FRAMES_AFTER_SPLIT)

    assert fingerprint(before_split, FINGERPRINT_KEY) == fingerprint(
        after_split, FINGERPRINT_KEY
    )


@pytest.mark.parametrize(
    "private_helper_frames",
    [FRAMES_BEFORE_SPLIT, FRAMES_AFTER_SPLIT],
    ids=["in-its-old-module", "in-its-new-module"],
)
def test_fingerprint_exception_ignores_leading_underscores_in_function_names(
    private_helper_frames: tuple[str, ...],
) -> None:
    private_helper = exception_record(frames=private_helper_frames)
    public_helper = exception_record(frames=FRAMES_AFTER_SPLIT_WITH_PUBLIC_HELPER)

    assert fingerprint(private_helper, FINGERPRINT_KEY) == fingerprint(
        public_helper, FINGERPRINT_KEY
    )


def test_fingerprint_exception_differs_when_a_function_is_renamed() -> None:
    renamed_frames = (
        *FRAMES_AFTER_SPLIT[:-1],
        _frame_header(
            "policyengine_api/services/report/regions.py", "_find_region", 12
        ),
    )
    original = exception_record(frames=FRAMES_AFTER_SPLIT)
    renamed = exception_record(frames=renamed_frames)

    assert fingerprint(original, FINGERPRINT_KEY) != fingerprint(
        renamed, FINGERPRINT_KEY
    )


def test_fingerprint_exception_merges_simulation_service_versions() -> None:
    first = exception_record(service_name="policyengine-simulation-py1-2-3")
    second = exception_record(service_name="policyengine-simulation-py1-2-4")

    assert fingerprint(first, FINGERPRINT_KEY) == fingerprint(second, FINGERPRINT_KEY)


@pytest.mark.parametrize(
    "change",
    [
        {"error_type": "ValueError"},
        {"frames": APPLICATION_FRAMES[:1]},
        {"service_name": "policyengine-simulation-entry"},
    ],
)
def test_fingerprint_exception_differs_by_type_frames_and_service(
    change: dict[str, object],
) -> None:
    original = exception_record()
    changed = exception_record(**change)

    assert fingerprint(original, FINGERPRINT_KEY) != fingerprint(
        changed, FINGERPRINT_KEY
    )


def test_fingerprint_is_the_same_when_truncation_drops_the_final_traceback() -> None:
    # The logging library keeps only the first 16,384 characters of a stack.
    short_stack = chained_stack(recursion_depth=20)
    long_stack = chained_stack(recursion_depth=120)[:16_384]
    assert "CalculationError" in short_stack
    assert "CalculationError" not in long_stack

    short = exception_record(
        error_type="CalculationError",
        frames=tuple(extract_frames(short_stack)),
    )
    long = exception_record(
        error_type="CalculationError",
        frames=tuple(extract_frames(long_stack)),
        stack_truncated=True,
    )

    assert fingerprint(short, FINGERPRINT_KEY) == fingerprint(long, FINGERPRINT_KEY)


def test_fingerprint_depends_on_the_key() -> None:
    record = exception_record()

    assert fingerprint(record, FINGERPRINT_KEY) != fingerprint(record, b"j" * 32)


def test_fingerprint_is_16_hex_characters() -> None:
    value = fingerprint(exception_record(), FINGERPRINT_KEY)

    assert re.fullmatch(r"[0-9a-f]{16}", value)


def test_fingerprint_key_parts_for_each_kind() -> None:
    exception = exception_record()
    message = message_record(
        attribute_error_type="TimeoutError",
        failure_category="upstream",
    )
    operation_message = message_record(route=None, operation_name="simulation.dispatch")
    failed_request = failed_request_record(status_code=502)

    assert fingerprint_parts(exception) == (
        "exception",
        "policyengine-api",
        "StaleDataError",
        "create_report",
        "create",
    )
    assert fingerprint_parts(message) == (
        "message",
        "policyengine-api",
        "/<country_id>/report",
        "failed to save",
        "TimeoutError",
        "upstream",
    )
    assert fingerprint_parts(operation_message)[2] == "simulation.dispatch"
    assert fingerprint_parts(failed_request) == (
        "failed_request",
        "policyengine-api",
        "/<country_id>/report",
        "502",
    )


@pytest.mark.parametrize(
    "change",
    [
        {"message_template": "failed to load"},
        {"route": "/<country_id>/calculate"},
        {"attribute_error_type": "ValueError"},
        {"failure_category": "validation"},
    ],
)
def test_fingerprint_message_differs_by_each_key_part(
    change: dict[str, object],
) -> None:
    original = message_record()
    changed = message_record(**change)

    assert fingerprint(original, FINGERPRINT_KEY) != fingerprint(
        changed, FINGERPRINT_KEY
    )


def test_fingerprint_failed_request_differs_by_status() -> None:
    first = failed_request_record(status_code=500)
    second = failed_request_record(status_code=504)

    assert fingerprint(first, FINGERPRINT_KEY) != fingerprint(second, FINGERPRINT_KEY)


@pytest.mark.parametrize("value", ["", "too-short", "x" * 31])
def test_fingerprint_key_rejects_a_secret_shorter_than_32_characters(
    value: str,
) -> None:
    with pytest.raises(ValueError, match="at least 32 characters"):
        fingerprint_key(value)


def test_fingerprint_key_accepts_a_64_character_hex_secret() -> None:
    assert fingerprint_key("ab" * 32) == ("ab" * 32).encode()
