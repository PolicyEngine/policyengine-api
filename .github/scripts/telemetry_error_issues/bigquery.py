"""Query error records and request counts through the BigQuery REST API."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlencode

from telemetry_error_issues.groups import RequestCount
from telemetry_error_issues.log_source import (
    DATASET_PATTERN,
    LOG_VIEW_PATTERN,
    checked_identifier,
)
from telemetry_error_issues.normalization import MISSING
from telemetry_error_issues.records import ErrorRecord
from telemetry_error_issues.transport import (
    ApiError,
    HttpRequest,
    HttpResponse,
    urllib_transport,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from telemetry_error_issues.log_source import LogSource
    from telemetry_error_issues.window import ReportingWindow

# Captures 'path", line N, in function' from each frame header of a Python
# traceback, including indented and "|"-prefixed exception group frames. It has
# one capturing group because BigQuery's REGEXP_EXTRACT_ALL allows only one,
# and the trailing newline skips a header that stack truncation cut short.
FRAME_PATTERN = r'File "([^"\n]+", line [0-9]+, in [^\s]+)\n'
# Matches everything after the first traceback of a chained exception, so the
# query can remove it before extracting frames. The logging library keeps only
# the start of a long stack, which can drop the final traceback; the first
# traceback is always kept, so frames from it give an exception the same
# fingerprint however long its stack is.
CHAINED_EXCEPTION_PATTERN = (
    r"(?s)\n\n(?:The above exception was the direct cause of the following "
    r"exception|During handling of the above exception, another exception "
    r"occurred):\n.*"
)

# A message's template is its first three whole words after removing quoted
# values, so values don't split one error into many groups. A single quote
# opens a value only after the start of the message or a character that is not
# a letter or digit; otherwise it is an apostrophe, as in "can't" or "users'".
# The query passes these to REGEXP_REPLACE and REGEXP_EXTRACT_ALL.
DOUBLE_QUOTED_PATTERN = r'"[^"]*"'
SINGLE_QUOTED_PATTERN = r"(^|[^A-Za-z0-9])'[^']*'"
TEMPLATE_WORD_PATTERN = r"\b[A-Za-z]+\b"

BIGQUERY_API = "https://bigquery.googleapis.com/bigquery/v2"
MAXIMUM_BYTES_BILLED = 5 * 1024**3
QUERY_WAIT_MILLISECONDS = 30_000
MAX_QUERY_POLLS = 40
UNIX_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

HEALTH_CHECK_ROUTES = (
    "/health",
    "/simulation-gateway-check",
    "/liveness-check",
    "/readiness-check",
)

# Each query reads the linked dataset's log view, whose name replaces
# {log_view} once it has passed LOG_VIEW_PATTERN: BigQuery takes no table name
# as a parameter. Only code-defined or normalized values leave BigQuery: stacks
# only as frame headers, messages only as templates (see DOUBLE_QUOTED_PATTERN),
# and identifiers only as SHA-256 hashes. Duplicate deliveries of one log entry
# are removed.
ERROR_RECORDS_QUERY = r"""
SELECT
  timestamp,
  JSON_VALUE(json_payload, '$."service.name"') AS service_name,
  JSON_VALUE(json_payload, '$."deployment.environment.name"') AS environment_name,
  JSON_VALUE(json_payload, '$."event.name"') AS event_name,
  JSON_VALUE(json_payload, '$."error.type"') AS error_type,
  JSON_VALUE(json_payload, '$."error.handled"') AS error_handled,
  REGEXP_EXTRACT_ALL(
    REGEXP_REPLACE(
      JSON_VALUE(json_payload, '$."error.stack"'), @chained_exception_pattern, ''
    ),
    @frame_pattern
  ) AS frames,
  COALESCE(LENGTH(JSON_VALUE(json_payload, '$."error.stack"')) >= 16384, FALSE)
    AS stack_truncated,
  ARRAY_TO_STRING(
    ARRAY(
      SELECT LOWER(word)
      FROM UNNEST(
        REGEXP_EXTRACT_ALL(
          REGEXP_REPLACE(
            REGEXP_REPLACE(
              JSON_VALUE(json_payload, '$.message'), @double_quoted_pattern, ''
            ),
            @single_quoted_pattern,
            r'\1'
          ),
          @template_word_pattern
        )
      ) AS word WITH OFFSET AS position
      WHERE position < 3
      ORDER BY position
    ),
    ' '
  ) AS message_template,
  JSON_VALUE(json_payload, '$.attributes.error_type') AS attribute_error_type,
  JSON_VALUE(json_payload, '$.attributes.failure_category') AS failure_category,
  JSON_VALUE(json_payload, '$."http.route"') AS route,
  JSON_VALUE(json_payload, '$."http.response.status_code"') AS status_code,
  JSON_VALUE(json_payload, '$."operation.name"') AS operation_name,
  TO_HEX(SHA256(JSON_VALUE(json_payload, '$."request.id"'))) AS request_key,
  TO_HEX(SHA256(JSON_VALUE(json_payload, '$.attributes.observability_id')))
    AS observability_key,
  TO_HEX(SHA256(COALESCE(
    JSON_VALUE(json_payload, '$.trace_id'),
    REGEXP_EXTRACT(trace, r'/traces/([0-9A-Fa-f]+)$')
  ))) AS trace_key
FROM `{log_view}`
WHERE timestamp >= @query_start AND timestamp < @window_end
  AND JSON_VALUE(json_payload, '$.schema_version') = 'policyengine.observability.v2'
  AND JSON_VALUE(json_payload, '$."service.namespace"') = @service_namespace
  AND severity_number >= 500
  AND COALESCE(JSON_VALUE(json_payload, '$."http.route"'), '')
    NOT IN UNNEST(@excluded_routes)
QUALIFY ROW_NUMBER() OVER (
  PARTITION BY insert_id, timestamp ORDER BY receive_timestamp
) = 1
"""

REQUEST_COUNTS_QUERY = r"""
WITH completed_requests AS (
  SELECT
    JSON_VALUE(json_payload, '$."service.name"') AS service_name,
    JSON_VALUE(json_payload, '$."deployment.environment.name"') AS environment_name,
    JSON_VALUE(json_payload, '$."http.route"') AS route
  FROM `{log_view}`
  WHERE timestamp >= @window_start AND timestamp < @window_end
    AND JSON_VALUE(json_payload, '$.schema_version') = 'policyengine.observability.v2'
    AND JSON_VALUE(json_payload, '$."service.namespace"') = @service_namespace
    AND JSON_VALUE(json_payload, '$."event.name"') = 'request.completed'
    AND COALESCE(JSON_VALUE(json_payload, '$."http.route"'), '')
      NOT IN UNNEST(@excluded_routes)
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY insert_id, timestamp ORDER BY receive_timestamp
  ) = 1
)
SELECT service_name, environment_name, route, COUNT(*) AS requests
FROM completed_requests
GROUP BY service_name, environment_name, route
"""


class BigQueryError(ApiError):
    """A BigQuery request failed."""

    service = "BigQuery"


class BigQueryTimeoutError(BigQueryError):
    """A BigQuery query job didn't complete within the polling limit."""


def _bigquery_boolean(text: str) -> bool:
    return text == "true"


def _bigquery_timestamp(text: str) -> datetime:
    """Convert microseconds since the epoch, as ``useInt64Timestamp`` returns."""
    return UNIX_EPOCH + timedelta(microseconds=int(text))


CELL_CONVERTERS: dict[str, Callable[[str], object]] = {
    "INTEGER": int,
    "INT64": int,
    "FLOAT": float,
    "FLOAT64": float,
    "BOOLEAN": _bigquery_boolean,
    "BOOL": _bigquery_boolean,
    "TIMESTAMP": _bigquery_timestamp,
}


def _convert_cell(field: Mapping[str, Any], value: object) -> object:
    """Convert one BigQuery REST value, which arrives as a string, to Python."""
    if value is None:
        return None
    if field.get("mode") == "REPEATED" and isinstance(value, list):
        item_field = {**field, "mode": "NULLABLE"}
        return [_convert_cell(item_field, item["v"]) for item in value]
    converter = CELL_CONVERTERS.get(str(field.get("type")), str)
    return converter(str(value))


def _convert_rows(response: Mapping[str, Any]) -> list[dict[str, object]]:
    fields = response["schema"]["fields"]
    return [
        {
            field["name"]: _convert_cell(field, cell["v"])
            for field, cell in zip(fields, row["f"], strict=True)
        }
        for row in response.get("rows", [])
    ]


class BigQueryClient:
    """Runs parameterized standard SQL queries through the BigQuery REST API."""

    def __init__(
        self,
        log_source: LogSource,
        access_token: str,
        transport: Callable[[HttpRequest], HttpResponse] = urllib_transport,
    ) -> None:
        """Run jobs in the log source's project against its linked dataset."""
        self.log_source = log_source
        self._access_token = access_token
        self._transport = transport
        project_id = quote(log_source.project_id, safe="")
        self._queries_url = f"{BIGQUERY_API}/projects/{project_id}/queries"

    def query(
        self, sql: str, parameters: list[dict[str, Any]], label: str
    ) -> list[dict[str, object]]:
        """Run ``sql`` and return every row as a dictionary of converted values."""
        body = {
            "query": sql,
            "useLegacySql": False,
            "parameterMode": "NAMED",
            "queryParameters": parameters,
            "defaultDataset": {
                "projectId": self.log_source.project_id,
                "datasetId": checked_identifier(
                    self.log_source.dataset, DATASET_PATTERN, "the log dataset"
                ),
            },
            "maximumBytesBilled": str(MAXIMUM_BYTES_BILLED),
            "labels": {"purpose": "telemetry-error-issues", "query": label},
            "timeoutMs": QUERY_WAIT_MILLISECONDS,
            "formatOptions": {"useInt64Timestamp": True},
        }
        response = self._send("POST", self._queries_url, body)
        job = response["jobReference"]
        for _ in range(MAX_QUERY_POLLS):
            if response.get("jobComplete"):
                break
            response = self._results(job, page_token=None)
        else:
            msg = "BigQuery query did not complete in time"
            raise BigQueryTimeoutError(msg)
        rows = _convert_rows(response)
        while response.get("pageToken"):
            response = self._results(job, page_token=response["pageToken"])
            rows.extend(_convert_rows(response))
        return rows

    def _results(
        self, job: Mapping[str, str], page_token: str | None
    ) -> dict[str, Any]:
        parameters = {
            "location": job["location"],
            "timeoutMs": str(QUERY_WAIT_MILLISECONDS),
            "formatOptions.useInt64Timestamp": "true",
        }
        if page_token:
            parameters["pageToken"] = page_token
        job_id = quote(job["jobId"], safe="")
        url = f"{self._queries_url}/{job_id}?{urlencode(parameters)}"
        return self._send("GET", url, None)

    def _send(
        self, method: str, url: str, body: Mapping[str, object] | None
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._access_token}"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        encoded = None if body is None else json.dumps(body).encode()
        response = self._transport(HttpRequest(method, url, headers, encoded))
        if response.status >= HTTPStatus.BAD_REQUEST:
            raise BigQueryError.from_response(response)
        return json.loads(response.body)


def _timestamp_parameter(name: str, moment: datetime) -> dict[str, Any]:
    return {
        "name": name,
        "parameterType": {"type": "TIMESTAMP"},
        "parameterValue": {"value": moment.astimezone(UTC).isoformat(sep=" ")},
    }


def _query_text(template: str, log_source: LogSource) -> str:
    """Name the log view in ``template``, once the name has passed its pattern."""
    view = checked_identifier(log_source.view, LOG_VIEW_PATTERN, "the log view")
    return template.format(log_view=view)


def _query_parameters(
    timestamps: Mapping[str, datetime], strings: Mapping[str, str]
) -> list[dict[str, Any]]:
    parameters = [
        _timestamp_parameter(name, value) for name, value in timestamps.items()
    ]
    parameters.extend(
        {
            "name": name,
            "parameterType": {"type": "STRING"},
            "parameterValue": {"value": value},
        }
        for name, value in strings.items()
    )
    parameters.append(
        {
            "name": "excluded_routes",
            "parameterType": {"type": "ARRAY", "arrayType": {"type": "STRING"}},
            "parameterValue": {
                "arrayValues": [{"value": route} for route in HEALTH_CHECK_ROUTES]
            },
        }
    )
    return parameters


def _text(value: object) -> str | None:
    return None if value is None or value == "" else str(value)


def _integer(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return int(value)
    return None


def _boolean(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    return {"true": True, "false": False}.get(str(value))


def error_record_from_row(row: Mapping[str, object]) -> ErrorRecord:
    """Build an ``ErrorRecord`` from one row of ``ERROR_RECORDS_QUERY``."""
    timestamp = row["timestamp"]
    if not isinstance(timestamp, datetime):
        msg = "an error record has no timestamp"
        raise TypeError(msg)
    frames = row["frames"]
    return ErrorRecord(
        timestamp=timestamp,
        service_name=_text(row["service_name"]) or MISSING,
        environment_name=_text(row["environment_name"]),
        event_name=_text(row["event_name"]),
        error_type=_text(row["error_type"]),
        error_handled=_boolean(row["error_handled"]),
        frames=tuple(map(str, frames)) if isinstance(frames, list) else (),
        stack_truncated=row["stack_truncated"] is True,
        message_template=_text(row["message_template"]),
        attribute_error_type=_text(row["attribute_error_type"]),
        failure_category=_text(row["failure_category"]),
        route=_text(row["route"]),
        status_code=_integer(row["status_code"]),
        operation_name=_text(row["operation_name"]),
        request_key=_text(row["request_key"]),
        observability_key=_text(row["observability_key"]),
        trace_key=_text(row["trace_key"]),
    )


def fetch_error_records(
    client: BigQueryClient, window: ReportingWindow
) -> list[ErrorRecord]:
    """Return the ERROR records of the window and the seven days before it."""
    parameters = _query_parameters(
        {"query_start": window.lookback_start, "window_end": window.end},
        {
            "service_namespace": client.log_source.service_namespace,
            "frame_pattern": FRAME_PATTERN,
            "chained_exception_pattern": CHAINED_EXCEPTION_PATTERN,
            "double_quoted_pattern": DOUBLE_QUOTED_PATTERN,
            "single_quoted_pattern": SINGLE_QUOTED_PATTERN,
            "template_word_pattern": TEMPLATE_WORD_PATTERN,
        },
    )
    sql = _query_text(ERROR_RECORDS_QUERY, client.log_source)
    rows = client.query(sql, parameters, "error-records")
    return [error_record_from_row(row) for row in rows]


def fetch_request_counts(
    client: BigQueryClient, window: ReportingWindow
) -> list[RequestCount]:
    """Return the requests each service completed per route in the window."""
    parameters = _query_parameters(
        {"window_start": window.start, "window_end": window.end},
        {"service_namespace": client.log_source.service_namespace},
    )
    sql = _query_text(REQUEST_COUNTS_QUERY, client.log_source)
    rows = client.query(sql, parameters, "request-counts")
    return [
        RequestCount(
            service_name=_text(row["service_name"]) or MISSING,
            environment_name=_text(row["environment_name"]),
            route=_text(row["route"]),
            requests=_integer(row["requests"]) or 0,
        )
        for row in rows
    ]
