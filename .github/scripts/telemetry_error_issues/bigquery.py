"""Query error records and request counts with the BigQuery client library.

The library starts each job, waits for it, reads every page of rows over the
REST API and converts each value to its Python type. Rows are read by
iterating the job's result, never with ``to_dataframe`` or ``to_arrow``,
which may use the BigQuery Storage Read API: the workflow's service account
has no role that can open a read session.
"""

from __future__ import annotations

from datetime import datetime
from http import HTTPStatus
from typing import TYPE_CHECKING

from google.api_core.exceptions import GoogleAPICallError
from google.cloud import bigquery
from google.oauth2.credentials import Credentials
from telemetry_error_issues.groups import RequestCount
from telemetry_error_issues.log_source import (
    DATASET_PATTERN,
    LOG_VIEW_PATTERN,
    checked_identifier,
)
from telemetry_error_issues.normalization import MISSING
from telemetry_error_issues.records import ErrorRecord
from telemetry_error_issues.transport import ERROR_REASON_PATTERN, ApiError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

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

MAXIMUM_BYTES_BILLED = 5 * 1024**3
# How long to wait for a query job to finish: 41 waits of 30 seconds, the
# limit the report had when it polled the REST API itself.
QUERY_TIMEOUT_SECONDS = 41 * 30

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
    """A BigQuery query job didn't complete within the time limit."""


QueryParameter = bigquery.ScalarQueryParameter | bigquery.ArrayQueryParameter


def library_client(project_id: str, access_token: str) -> bigquery.Client:
    """Return a library client that runs jobs in ``project_id`` as the token's owner.

    google-github-actions/auth makes the access token and writes no credentials
    file, so the client gets the token itself and never looks for other
    credentials.
    """
    credentials = Credentials(token=access_token)
    return bigquery.Client(project=project_id, credentials=credentials)


def _error_reason(errors: Sequence[object], status: int) -> str:
    """Return the error's reason code, else the HTTP reason phrase.

    The library's message can repeat the query and values from the request,
    so only a short code-defined reason such as ``invalidQuery`` is kept.
    """
    reason = errors[0].get("reason") if errors and isinstance(errors[0], dict) else None
    if isinstance(reason, str) and ERROR_REASON_PATTERN.match(reason):
        return reason
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return "unknown"


def _bigquery_error(error: GoogleAPICallError) -> BigQueryError:
    """Describe a library error by its HTTP status and reason, never its message."""
    if error.code is None:
        return BigQueryError("BigQuery request failed")
    status = int(error.code)
    reason = _error_reason(error.errors, status)
    message = f"BigQuery request failed: HTTP {status} {reason}"
    return BigQueryError(message, status=status, reason=reason)


class BigQueryClient:
    """Runs parameterized standard SQL queries against the linked log dataset."""

    def __init__(
        self,
        log_source: LogSource,
        access_token: str,
        client_factory: Callable[[str, str], bigquery.Client] = library_client,
    ) -> None:
        """Run jobs in the log source's project against its linked dataset."""
        self.log_source = log_source
        self._client = client_factory(log_source.project_id, access_token)

    def query(
        self, sql: str, parameters: list[QueryParameter], label: str
    ) -> list[dict[str, object]]:
        """Run ``sql`` and return every row as a dictionary of its values."""
        dataset = checked_identifier(
            self.log_source.dataset, DATASET_PATTERN, "the log dataset"
        )
        job_config = bigquery.QueryJobConfig(
            query_parameters=parameters,
            default_dataset=bigquery.DatasetReference(
                self.log_source.project_id, dataset
            ),
            maximum_bytes_billed=MAXIMUM_BYTES_BILLED,
            use_legacy_sql=False,
            labels={"purpose": "telemetry-error-issues", "query": label},
        )
        try:
            job = self._client.query(sql, job_config=job_config)
            rows = job.result(timeout=QUERY_TIMEOUT_SECONDS)
            return [dict(row.items()) for row in rows]
        except GoogleAPICallError as error:
            raise _bigquery_error(error) from error
        except TimeoutError as error:
            msg = "BigQuery query did not complete in time"
            raise BigQueryTimeoutError(msg) from error


def _query_text(template: str, log_source: LogSource) -> str:
    """Name the log view in ``template``, once the name has passed its pattern."""
    view = checked_identifier(log_source.view, LOG_VIEW_PATTERN, "the log view")
    return template.format(log_view=view)


def _query_parameters(
    timestamps: Mapping[str, datetime], strings: Mapping[str, str]
) -> list[QueryParameter]:
    parameters: list[QueryParameter] = [
        bigquery.ScalarQueryParameter(name, "TIMESTAMP", value)
        for name, value in timestamps.items()
    ]
    parameters.extend(
        bigquery.ScalarQueryParameter(name, "STRING", value)
        for name, value in strings.items()
    )
    parameters.append(
        bigquery.ArrayQueryParameter(
            "excluded_routes", "STRING", list(HEALTH_CHECK_ROUTES)
        )
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
