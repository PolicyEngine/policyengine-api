"""Tests for telemetry_error_issues.bigquery: the queries, client and rows."""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest
from google.api_core.exceptions import BadRequest, Forbidden, ServiceUnavailable
from google.cloud import bigquery
from telemetry_error_issues.bigquery import (
    CHAINED_EXCEPTION_PATTERN,
    DOUBLE_QUOTED_PATTERN,
    ERROR_RECORDS_QUERY,
    FRAME_PATTERN,
    QUERY_TIMEOUT_SECONDS,
    REQUEST_COUNTS_QUERY,
    SINGLE_QUOTED_PATTERN,
    TEMPLATE_WORD_PATTERN,
    BigQueryClient,
    BigQueryError,
    BigQueryTimeoutError,
    error_record_from_row,
    fetch_error_records,
    fetch_request_counts,
    library_client,
)
from telemetry_error_issues.window import reporting_window

from tests.unit.telemetry_error_issues.bigquery_support import (
    ACCESS_TOKEN,
    FakeBigQueryClient,
    sent_parameters,
)
from tests.unit.telemetry_error_issues.report_support import (
    APPLICATION_FRAMES,
    LOG_SOURCE,
    REPORT_DATE,
    WINDOW_NOON,
    exception_record,
    request_count,
)


def _client(fake: FakeBigQueryClient, log_source: object = LOG_SOURCE) -> object:
    return BigQueryClient(log_source, ACCESS_TOKEN, fake.factory)


def _string_parameter(name: str, value: str) -> bigquery.ScalarQueryParameter:
    return bigquery.ScalarQueryParameter(name, "STRING", value)


def test_bigquery_error_query_request_limits_cost_and_names_its_parameters() -> None:
    fake = FakeBigQueryClient()

    fetch_error_records(_client(fake), reporting_window(REPORT_DATE))

    sql, job_config = fake.queries[0]
    parameters = sent_parameters(fake)
    assert fake.created_with == [("policyengine-observability", ACCESS_TOKEN)]
    assert job_config.use_legacy_sql is False
    assert job_config.maximum_bytes_billed == 5 * 1024**3
    assert job_config.labels == {
        "purpose": "telemetry-error-issues",
        "query": "error-records",
    }
    assert job_config.default_dataset == bigquery.DatasetReference(
        "policyengine-observability", "observability_logs"
    )
    assert "FROM `_AllLogs`" in sql
    assert parameters["query_start"] == bigquery.ScalarQueryParameter(
        "query_start", "TIMESTAMP", datetime(2026, 10, 13, 4, 0, tzinfo=UTC)
    )
    assert parameters["window_end"] == bigquery.ScalarQueryParameter(
        "window_end", "TIMESTAMP", datetime(2026, 10, 21, 4, 0, tzinfo=UTC)
    )
    assert parameters["service_namespace"] == _string_parameter(
        "service_namespace", "policyengine.api-v1"
    )
    for name, pattern in (
        ("frame_pattern", FRAME_PATTERN),
        ("chained_exception_pattern", CHAINED_EXCEPTION_PATTERN),
        ("double_quoted_pattern", DOUBLE_QUOTED_PATTERN),
        ("single_quoted_pattern", SINGLE_QUOTED_PATTERN),
        ("template_word_pattern", TEMPLATE_WORD_PATTERN),
    ):
        assert parameters[name] == _string_parameter(name, pattern)
    assert parameters["excluded_routes"] == bigquery.ArrayQueryParameter(
        "excluded_routes",
        "STRING",
        ["/health", "/simulation-gateway-check", "/liveness-check", "/readiness-check"],
    )


def test_bigquery_queries_name_the_configured_dataset_and_view() -> None:
    fake = FakeBigQueryClient()
    log_source = LOG_SOURCE._replace(dataset="linked_logs", view="_Requests")
    client = _client(fake, log_source)

    fetch_error_records(client, reporting_window(REPORT_DATE))
    fetch_request_counts(client, reporting_window(REPORT_DATE))

    for sql, job_config in fake.queries:
        assert job_config.default_dataset.dataset_id == "linked_logs"
        assert "FROM `_Requests`" in sql
        assert "_AllLogs" not in sql


@pytest.mark.parametrize(
    "unsafe_names",
    [
        {"view": "_AllLogs` WHERE TRUE --"},
        {"view": "_AllLogs\n"},
        {"view": ""},
        {"dataset": "observability_logs.other"},
        {"dataset": "logs; DROP TABLE logs"},
    ],
)
def test_bigquery_refuses_a_dataset_or_view_that_is_not_an_identifier(
    unsafe_names: dict[str, str],
) -> None:
    fake = FakeBigQueryClient()
    client = _client(fake, LOG_SOURCE._replace(**unsafe_names))

    with pytest.raises(ValueError, match="is not a valid name"):
        fetch_error_records(client, reporting_window(REPORT_DATE))

    assert fake.queries == []


def test_bigquery_error_query_filters_application_error_records() -> None:
    sql = ERROR_RECORDS_QUERY

    assert "FROM `{log_view}`" in sql
    assert "timestamp >= @query_start AND timestamp < @window_end" in sql
    assert (
        "JSON_VALUE(json_payload, '$.schema_version') = "
        "'policyengine.observability.v2'" in sql
    )
    assert (
        "JSON_VALUE(json_payload, '$.\"service.namespace\"') = @service_namespace"
        in sql
    )
    assert "policyengine.api-v1" not in sql
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
    fake = FakeBigQueryClient()

    fetch_request_counts(_client(fake), reporting_window(REPORT_DATE))

    sent_sql, job_config = fake.queries[0]
    parameters = sent_parameters(fake)
    assert "JSON_VALUE(json_payload, '$.\"event.name\"') = 'request.completed'" in sql
    assert "COUNT(*) AS requests" in sql
    assert "GROUP BY service_name, environment_name, route" in sql
    assert "timestamp >= @window_start AND timestamp < @window_end" in sql
    assert parameters["window_start"] == bigquery.ScalarQueryParameter(
        "window_start", "TIMESTAMP", datetime(2026, 10, 20, 4, 0, tzinfo=UTC)
    )
    assert parameters["service_namespace"] == _string_parameter(
        "service_namespace", "policyengine.api-v1"
    )
    assert "FROM `_AllLogs`" in sent_sql
    assert job_config.labels["query"] == "request-counts"


def test_bigquery_client_reads_every_row_the_job_yields() -> None:
    rows = [{"name": "first", "count": 1}, {"name": "second", "count": 2}]
    fake = FakeBigQueryClient({"test": rows})

    result = _client(fake).query("SELECT 1", [], "test")

    assert result == rows
    # 41 waits of 30 seconds, the limit of the REST client this replaced.
    assert fake.result_timeouts == [QUERY_TIMEOUT_SECONDS] == [1_230]


def test_bigquery_client_reports_a_job_that_does_not_finish_in_time() -> None:
    fake = FakeBigQueryClient(error=TimeoutError())

    with pytest.raises(BigQueryTimeoutError, match="did not complete"):
        _client(fake).query("SELECT 1", [], "test")


def test_bigquery_library_error_reports_only_the_status_and_reason() -> None:
    error = BadRequest(
        "SENTINEL value echoed from a row",
        errors=[{"reason": "invalidQuery", "message": "SENTINEL detail"}],
    )
    fake = FakeBigQueryClient(error=error)

    with pytest.raises(BigQueryError) as raised:
        _client(fake).query("SELECT 1", [], "test")

    assert str(raised.value) == "BigQuery request failed: HTTP 400 invalidQuery"
    assert raised.value.status == 400
    assert raised.value.reason == "invalidQuery"


def test_bigquery_library_error_without_a_reason_code_uses_the_status_phrase() -> None:
    fake = FakeBigQueryClient(error=ServiceUnavailable("SENTINEL <html>"))

    with pytest.raises(BigQueryError) as raised:
        _client(fake).query("SELECT 1", [], "test")

    assert str(raised.value) == "BigQuery request failed: HTTP 503 Service Unavailable"


@pytest.mark.parametrize("reason", ["SENTINEL: 'value'", "a" * 61, 7])
def test_bigquery_library_error_hides_a_reason_that_is_not_a_short_code(
    reason: object,
) -> None:
    fake = FakeBigQueryClient(error=Forbidden("SENTINEL", errors=[{"reason": reason}]))

    with pytest.raises(BigQueryError) as raised:
        _client(fake).query("SELECT 1", [], "test")

    assert str(raised.value) == "BigQuery request failed: HTTP 403 Forbidden"


def test_bigquery_library_client_sends_the_access_token_for_the_project() -> None:
    client = library_client("policyengine-observability", ACCESS_TOKEN)

    assert isinstance(client, bigquery.Client)
    assert client.project == "policyengine-observability"
    assert client._credentials.token == ACCESS_TOKEN


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
    fake = FakeBigQueryClient({"request-counts": rows})

    counts = fetch_request_counts(_client(fake), reporting_window(REPORT_DATE))

    assert counts == [
        request_count("/<country_id>/report", 120),
    ]
