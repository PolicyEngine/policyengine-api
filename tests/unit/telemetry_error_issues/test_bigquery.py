"""Tests for telemetry_error_issues.bigquery: the queries, client and rows."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import pytest
from telemetry_error_issues.bigquery import (
    CHAINED_EXCEPTION_PATTERN,
    DOUBLE_QUOTED_PATTERN,
    ERROR_RECORDS_QUERY,
    FRAME_PATTERN,
    REQUEST_COUNTS_QUERY,
    SINGLE_QUOTED_PATTERN,
    TEMPLATE_WORD_PATTERN,
    BigQueryClient,
    BigQueryError,
    error_record_from_row,
    fetch_error_records,
    fetch_request_counts,
)
from telemetry_error_issues.transport import HttpResponse
from telemetry_error_issues.window import reporting_window

from tests.unit.telemetry_error_issues.bigquery_support import (
    ACCESS_TOKEN,
    FakeTransport,
    json_response,
    query_response,
    sent_parameters,
)
from tests.unit.telemetry_error_issues.report_support import (
    APPLICATION_FRAMES,
    REPORT_DATE,
    WINDOW_NOON,
    exception_record,
    request_count,
)

STRING_FIELD = {"name": "name", "type": "STRING", "mode": "NULLABLE"}


def _client(transport: FakeTransport) -> object:
    return BigQueryClient("policyengine-observability", ACCESS_TOKEN, transport)


def test_bigquery_error_query_request_limits_cost_and_names_its_parameters() -> None:
    transport = FakeTransport([json_response(query_response([], []))])
    window = reporting_window(REPORT_DATE)

    fetch_error_records(_client(transport), window)

    request = transport.requests[0]
    body = transport.json_body(0)
    parameters = sent_parameters(transport)
    assert request.method == "POST"
    assert request.url == (
        "https://bigquery.googleapis.com/bigquery/v2/projects/"
        "policyengine-observability/queries"
    )
    assert request.headers["Authorization"] == f"Bearer {ACCESS_TOKEN}"
    assert body["useLegacySql"] is False
    assert body["parameterMode"] == "NAMED"
    assert body["maximumBytesBilled"] == str(5 * 1024**3)
    assert body["labels"] == {
        "purpose": "telemetry-error-issues",
        "query": "error-records",
    }
    assert body["defaultDataset"] == {
        "projectId": "policyengine-observability",
        "datasetId": "observability_logs",
    }
    assert body["formatOptions"] == {"useInt64Timestamp": True}
    assert parameters["query_start"]["parameterType"] == {"type": "TIMESTAMP"}
    assert parameters["query_start"]["parameterValue"]["value"] == (
        "2026-10-13 04:00:00+00:00"
    )
    assert parameters["window_end"]["parameterValue"]["value"] == (
        "2026-10-21 04:00:00+00:00"
    )
    assert parameters["frame_pattern"]["parameterValue"]["value"] == (FRAME_PATTERN)
    assert parameters["chained_exception_pattern"]["parameterValue"]["value"] == (
        CHAINED_EXCEPTION_PATTERN
    )
    for name, pattern in (
        ("double_quoted_pattern", DOUBLE_QUOTED_PATTERN),
        ("single_quoted_pattern", SINGLE_QUOTED_PATTERN),
        ("template_word_pattern", TEMPLATE_WORD_PATTERN),
    ):
        assert parameters[name]["parameterValue"]["value"] == pattern
    assert [
        item["value"]
        for item in parameters["excluded_routes"]["parameterValue"]["arrayValues"]
    ] == ["/health", "/simulation-gateway-check", "/liveness-check", "/readiness-check"]


def test_bigquery_error_query_filters_application_error_records() -> None:
    sql = ERROR_RECORDS_QUERY

    assert "FROM `_AllLogs`" in sql
    assert "timestamp >= @query_start AND timestamp < @window_end" in sql
    assert (
        "JSON_VALUE(json_payload, '$.schema_version') = "
        "'policyengine.observability.v2'" in sql
    )
    assert (
        "JSON_VALUE(json_payload, '$.\"service.namespace\"') = "
        "'policyengine.api-v1'" in sql
    )
    assert "severity_number >= 500" in sql
    assert "NOT IN UNNEST(@excluded_routes)" in sql
    assert "QUALIFY ROW_NUMBER() OVER" in sql


def test_bigquery_error_query_reads_stacks_and_messages_only_through_expressions():
    sql = ERROR_RECORDS_QUERY
    stack = "JSON_VALUE(json_payload, '$.\"error.stack\"')"

    assert sql.count("error.stack") == 2
    assert (
        "  REGEXP_EXTRACT_ALL(\n"
        "    REGEXP_REPLACE(\n"
        f"      {stack}, @chained_exception_pattern, ''\n"
        "    ),\n"
        "    @frame_pattern\n"
        "  ) AS frames"
    ) in sql
    assert f"LENGTH({stack}) >= 16384" in sql
    assert sql.count("$.message") == 1
    assert (
        "          REGEXP_REPLACE(\n"
        "            REGEXP_REPLACE(\n"
        "              JSON_VALUE(json_payload, '$.message'), "
        "@double_quoted_pattern, ''\n"
        "            ),\n"
        "            @single_quoted_pattern,\n"
        "            r'\\1'\n"
        "          ),\n"
        "          @template_word_pattern\n"
    ) in sql
    assert "error.message" not in sql
    assert "SELECT *" not in sql
    assert "json_payload AS" not in sql


@pytest.mark.parametrize(
    "identifier",
    [
        "JSON_VALUE(json_payload, '$.\"request.id\"')",
        "JSON_VALUE(json_payload, '$.attributes.observability_id')",
    ],
)
def test_bigquery_error_query_hashes_identifiers(identifier: str) -> None:
    sql = ERROR_RECORDS_QUERY

    assert sql.count(identifier) == 1
    assert f"TO_HEX(SHA256({identifier}))" in sql


def _message_template(message: str) -> str:
    """Build the template the way the query does, with RE2's ASCII word rules."""
    without_double_quotes = re.sub(DOUBLE_QUOTED_PATTERN, "", message)
    without_quotes = re.sub(SINGLE_QUOTED_PATTERN, r"\1", without_double_quotes)
    words = re.findall(TEMPLATE_WORD_PATTERN, without_quotes, re.ASCII)
    return " ".join(word.lower() for word in words[:3])


def test_bigquery_template_keeps_words_around_an_apostrophe() -> None:
    templates = {
        _message_template(f"Can't load policy '{value}'")
        for value in ("alpha", "beta", "gamma")
    }

    assert templates == {"can t load"}


@pytest.mark.parametrize(
    ("message", "template"),
    [
        ("Failed to save 'report 12' for user", "failed to save"),
        ("'SENTINEL' could not be parsed", "could not be"),
        ('Missing "SENTINEL" in household input', "missing in household"),
        ("Timeout after 30s calling the simulation API", "timeout after calling"),
        ("The users' policies 'SENTINEL' failed", "the users policies"),
    ],
)
def test_bigquery_template_drops_quoted_values_and_partial_words(
    message: str, template: str
) -> None:
    assert _message_template(message) == template


def test_bigquery_error_query_hashes_the_trace() -> None:
    sql = ERROR_RECORDS_QUERY

    assert "TO_HEX(SHA256(COALESCE(" in sql
    assert sql.count("$.trace_id") == 1


def test_bigquery_request_count_query_counts_completed_requests_in_the_window() -> None:
    sql = REQUEST_COUNTS_QUERY
    transport = FakeTransport([json_response(query_response([], []))])

    fetch_request_counts(_client(transport), reporting_window(REPORT_DATE))

    parameters = sent_parameters(transport)
    assert "JSON_VALUE(json_payload, '$.\"event.name\"') = 'request.completed'" in sql
    assert "COUNT(*) AS requests" in sql
    assert "GROUP BY service_name, environment_name, route" in sql
    assert "timestamp >= @window_start AND timestamp < @window_end" in sql
    assert parameters["window_start"]["parameterValue"]["value"] == (
        "2026-10-20 04:00:00+00:00"
    )
    assert transport.json_body(0)["labels"]["query"] == "request-counts"


def test_bigquery_client_polls_until_the_job_completes() -> None:
    transport = FakeTransport(
        [
            json_response(query_response([], [], job_complete=False)),
            json_response(query_response([], [], job_complete=False)),
            json_response(query_response([STRING_FIELD], [["done"]])),
        ],
    )

    rows = _client(transport).query("SELECT 1", [], "test")

    assert rows == [{"name": "done"}]
    poll = urlparse(transport.requests[1].url)
    assert transport.requests[1].method == "GET"
    assert poll.path.endswith("/projects/policyengine-observability/queries/job-1")
    assert parse_qs(poll.query)["location"] == ["US"]
    assert parse_qs(poll.query)["formatOptions.useInt64Timestamp"] == ["true"]


def test_bigquery_client_follows_page_tokens() -> None:
    transport = FakeTransport(
        [
            json_response(
                query_response([STRING_FIELD], [["first"]], page_token="page-2"),
            ),
            json_response(query_response([STRING_FIELD], [["second"]])),
        ],
    )

    rows = _client(transport).query("SELECT 1", [], "test")

    assert rows == [{"name": "first"}, {"name": "second"}]
    page = parse_qs(urlparse(transport.requests[1].url).query)
    assert page["pageToken"] == ["page-2"]
    assert page["location"] == ["US"]


def test_bigquery_client_gives_up_on_a_job_that_never_completes() -> None:
    pending = json_response(query_response([], [], job_complete=False))
    transport = FakeTransport([pending] * 200)

    with pytest.raises(BigQueryError, match="did not complete"):
        _client(transport).query("SELECT 1", [], "test")


def test_bigquery_client_converts_row_values_from_strings() -> None:
    fields = [
        {"name": "text", "type": "STRING", "mode": "NULLABLE"},
        {"name": "count", "type": "INTEGER", "mode": "NULLABLE"},
        {"name": "flag", "type": "BOOLEAN", "mode": "NULLABLE"},
        {"name": "moment", "type": "TIMESTAMP", "mode": "NULLABLE"},
        {"name": "items", "type": "STRING", "mode": "REPEATED"},
        {"name": "missing", "type": "INTEGER", "mode": "NULLABLE"},
    ]
    row = ["value", "42", "true", "1792512000000001", ["a", "b"], None]
    transport = FakeTransport([json_response(query_response(fields, [row]))])

    rows = _client(transport).query("SELECT 1", [], "test")

    assert rows == [
        {
            "text": "value",
            "count": 42,
            "flag": True,
            "moment": datetime(2026, 10, 20, 16, 0, 0, 1, tzinfo=UTC),
            "items": ["a", "b"],
            "missing": None,
        }
    ]


def test_bigquery_http_error_reports_only_the_status_and_reason() -> None:
    error_body = {
        "error": {
            "code": 400,
            "message": "SENTINEL value echoed from a row",
            "errors": [{"reason": "invalidQuery", "message": "SENTINEL detail"}],
        }
    }
    transport = FakeTransport(
        [json_response(error_body, status=400, reason="Bad Request")],
    )

    with pytest.raises(BigQueryError) as raised:
        _client(transport).query("SELECT 1", [], "test")

    assert str(raised.value) == "BigQuery request failed: HTTP 400 invalidQuery"
    assert raised.value.status == 400
    assert raised.value.reason == "invalidQuery"


def test_bigquery_http_error_without_a_json_reason_uses_the_status_phrase() -> None:
    response = HttpResponse(
        status=503, reason="Service Unavailable", headers={}, body=b"SENTINEL <html>"
    )
    transport = FakeTransport([response])

    with pytest.raises(BigQueryError) as raised:
        _client(transport).query("SELECT 1", [], "test")

    assert str(raised.value) == "BigQuery request failed: HTTP 503 Service Unavailable"


def test_bigquery_rows_become_error_records() -> None:
    row = {
        "timestamp": WINDOW_NOON,
        "service_name": "policyengine-api",
        "environment_name": "production",
        "event_name": "exception.recorded",
        "error_type": "StaleDataError",
        "error_handled": "false",
        "frames": list(APPLICATION_FRAMES),
        "stack_truncated": False,
        "message_template": "",
        "attribute_error_type": None,
        "failure_category": None,
        "route": "/<country_id>/report",
        "status_code": "500",
        "operation_name": None,
        "request_key": "aa",
        "observability_key": None,
        "trace_key": "bb",
    }

    record = error_record_from_row(row)

    assert record == exception_record(request_key="aa", trace_key="bb")


def test_bigquery_rows_tolerate_missing_and_malformed_values() -> None:
    row = {
        "timestamp": WINDOW_NOON,
        "service_name": None,
        "environment_name": None,
        "event_name": None,
        "error_type": None,
        "error_handled": "SENTINEL",
        "frames": None,
        "stack_truncated": None,
        "message_template": None,
        "attribute_error_type": None,
        "failure_category": None,
        "route": None,
        "status_code": "SENTINEL",
        "operation_name": None,
        "request_key": None,
        "observability_key": None,
        "trace_key": None,
    }

    record = error_record_from_row(row)

    assert record.service_name == "-"
    assert record.error_handled is None
    assert record.frames == ()
    assert record.stack_truncated is False
    assert record.status_code is None


def test_bigquery_rows_become_request_counts() -> None:
    rows = [
        {
            "service_name": "policyengine-api",
            "environment_name": "production",
            "route": "/<country_id>/report",
            "requests": 120,
        }
    ]
    transport = FakeTransport(
        [
            json_response(
                query_response(
                    [
                        {"name": "service_name", "type": "STRING"},
                        {"name": "environment_name", "type": "STRING"},
                        {"name": "route", "type": "STRING"},
                        {"name": "requests", "type": "INTEGER"},
                    ],
                    [list(map(str, rows[0].values()))],
                ),
            )
        ],
    )

    counts = fetch_request_counts(_client(transport), reporting_window(REPORT_DATE))

    assert counts == [
        request_count("/<country_id>/report", 120),
    ]
