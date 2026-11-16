"""Runtime events for v2 metadata reads that fail with a generic 503 or a 500.

The response stays the generic one, but the observability runtime records one
event that says what failed: the route and request ID, which the runtime takes
from the request it is serving, then the response status, the caught error's
class (``error_type``), a failure category that tells a catalog outage from an
unexpected failure, the class of each error in its ``__cause__`` chain, the
driver's SQLSTATE and whether SQLAlchemy found the connection lost. The
scheduled error-issue job groups such an event by route, ``error_type`` and
``failure_category``. The event never records an error's message, which can
carry the SQL statement, its parameters, host names, addresses or credentials.

The tests serve each request through a runtime with the process runtime's
settings whose records go to a list, so they see the event as the runtime
writes it, request context included.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest
from policyengine_observability import CustomLogDestination, OTelConfig, configure
from psycopg import errors as psycopg_errors
from sqlalchemy.exc import DBAPIError

from policyengine_api import observability
from policyengine_api.data.v2.catalog.catalog_selection_validation import (
    MetadataCatalogUnavailableError,
)
from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.fastapi_routes.v2.metadata.read_failure_support import (
    MAX_NAMED_CAUSES,
    read_failure_attributes,
)
from policyengine_api.services.v2.metadata.validators import (
    CatalogValuesPrunedError,
    ParameterSearchFileUnavailableError,
    ParameterTreeUnavailableError,
)
from tests.fixtures.v2_metadata_routes import ResourceReader, metadata_route_client

if TYPE_CHECKING:
    from collections.abc import Iterator

    from policyengine_observability import ObservabilityRuntime

ROUTE = "/v2/parameter-values"
PATH = f"{ROUTE}?country_id=us&limit=1"
FAILURE_EVENT = "v2_metadata_read_failed"
GENERIC_503 = {"status": "error", "message": "V2 metadata catalog is unavailable"}
GENERIC_500 = {"status": "error", "message": "V2 metadata query failed"}
STATEMENT = "SELECT parameter_values.id FROM parameter_values WHERE country_id = %(c)s"
PARAMETER_VALUE = "us-secret-parameter-value"
SENSITIVE_TEXT = (
    STATEMENT,
    PARAMETER_VALUE,
    "pooler.example.internal",
    "10.12.0.7",
    "hunter2",
    "postgresql://",
)
LOST_CONNECTION_CAUSES = "sqlalchemy.exc.OperationalError, psycopg.errors.AdminShutdown"


class RecordList:
    """A runtime destination that keeps every record it is given."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def write(self, record: dict[str, Any]) -> None:
        self.records.append(record)

    def failures(self) -> list[dict[str, Any]]:
        return [
            record
            for record in self.records
            if record.get("event.name") == FAILURE_EVENT
        ]


class FailingRuntime:
    def event(self, *_arguments: object, **_details: object) -> None:
        msg = "the observability runtime is down"
        raise RuntimeError(msg)


@pytest.fixture
def recorded(monkeypatch) -> Iterator[tuple[RecordList, ObservabilityRuntime]]:
    """Serve requests through a runtime whose records the test can read.

    It keeps the process runtime's settings and replaces only where records go,
    with OpenTelemetry export off.
    """
    record_list = RecordList()
    process_config = observability.get_runtime().config
    runtime = configure(
        replace(
            process_config,
            logging=replace(
                process_config.logging,
                destinations=(
                    CustomLogDestination(
                        name="test-records",
                        writer_factory=lambda: record_list,
                        delivery="inline",
                    ),
                ),
            ),
            otel=OTelConfig(enabled=False),
        )
    )
    monkeypatch.setattr(observability, "get_runtime", lambda: runtime)
    try:
        yield record_list, runtime
    finally:
        runtime.shutdown()


def _get(reader: ResourceReader, runtime: ObservabilityRuntime | None = None):
    client = metadata_route_client(lambda: reader, observability_runtime=runtime)
    return client.get(PATH)


def _reader_failing_with(error: BaseException) -> ResourceReader:
    return ResourceReader({"list_parameter_values": None}, error=error)


def _qualified_name(error_class: type[BaseException]) -> str:
    return f"{error_class.__module__}.{error_class.__qualname__}"


def _lost_connection() -> DBAPIError:
    """Return SQLAlchemy's error for a connection the server ended mid-query.

    psycopg raises ``AdminShutdown`` (SQLSTATE 57P01), and SQLAlchemy wraps it
    as it does, raising its error from psycopg's. Every message names the
    statement, a parameter, the pooler's host and address and a password, as a
    driver's message can.
    """
    driver_error = psycopg_errors.AdminShutdown(
        "terminating connection due to administrator command: "
        "postgresql://reader:hunter2@pooler.example.internal (10.12.0.7)"
    )
    database_error = DBAPIError.instance(
        STATEMENT,
        {"c": PARAMETER_VALUE},
        driver_error,
        psycopg_errors.Error,
        connection_invalidated=True,
    )
    database_error.__cause__ = driver_error
    return database_error


def _caused_by(error: BaseException, cause: BaseException) -> BaseException:
    error.__cause__ = cause
    return error


def _assert_nothing_sensitive(record: dict[str, Any]) -> None:
    written = repr(record)
    for text in SENSITIVE_TEXT:
        assert text not in written


def test_a_lost_connection_answers_the_same_503_and_records_its_cause(
    recorded,
) -> None:
    record_list, runtime = recorded
    error = _caused_by(
        MetadataCatalogUnavailableError(f"catalog read failed: {STATEMENT}"),
        _lost_connection(),
    )

    response = _get(_reader_failing_with(error), runtime)
    [record] = record_list.failures()

    assert (response.status_code, response.json()) == (503, GENERIC_503)
    assert record["severity"] == "ERROR"
    assert record["http.route"] == ROUTE
    assert record["request.id"] == response.headers["x-policyengine-request-id"]
    assert record["attributes"] == {
        "http.response.status_code": 503,
        "error_type": _qualified_name(MetadataCatalogUnavailableError),
        "failure_category": "v2_metadata_catalog_unavailable",
        "error.cause_types": LOST_CONNECTION_CAUSES,
        "database.sqlstate": "57P01",
        "database.connection_invalidated": True,
    }
    _assert_nothing_sensitive(record)


def test_an_unexpected_failure_answers_the_same_500_and_records_its_cause(
    recorded,
) -> None:
    record_list, runtime = recorded
    error = _caused_by(RuntimeError(f"failed on {STATEMENT}"), _lost_connection())

    response = _get(_reader_failing_with(error), runtime)
    [record] = record_list.failures()

    assert (response.status_code, response.json()) == (500, GENERIC_500)
    assert (record["severity"], record["http.route"]) == ("ERROR", ROUTE)
    assert record["attributes"] == {
        "http.response.status_code": 500,
        "error_type": "builtins.RuntimeError",
        "failure_category": "v2_metadata_query_failed",
        "error.cause_types": LOST_CONNECTION_CAUSES,
        "database.sqlstate": "57P01",
        "database.connection_invalidated": True,
    }
    _assert_nothing_sensitive(record)


@pytest.mark.parametrize(
    "error",
    [
        MetadataCatalogUnavailableError("catalog connection refused"),
        V2ConfigurationError("V2_DATABASE_URL is not set"),
    ],
    ids=["catalog-unavailable", "configuration"],
)
def test_a_failure_without_a_database_cause_records_only_its_class(
    recorded, error: BaseException
) -> None:
    record_list, runtime = recorded

    response = _get(_reader_failing_with(error), runtime)
    [record] = record_list.failures()

    assert (response.status_code, response.json()) == (503, GENERIC_503)
    assert record["attributes"] == {
        "http.response.status_code": 503,
        "error_type": _qualified_name(type(error)),
        "failure_category": "v2_metadata_catalog_unavailable",
    }


@pytest.mark.parametrize(
    "error",
    [
        CatalogValuesPrunedError("pruned", running_version=True),
        ParameterTreeUnavailableError("5.0.1 has no parameter tree"),
        ParameterSearchFileUnavailableError("5.0.1 has no parameter search file"),
    ],
    ids=["pruned-version", "no-parameter-tree", "no-search-file"],
)
def test_an_answer_with_its_own_message_records_no_failure(
    recorded, error: BaseException
) -> None:
    record_list, runtime = recorded

    response = _get(_reader_failing_with(error), runtime)

    assert response.status_code == 503
    assert response.json()["message"] == str(error)
    assert record_list.failures() == []


@pytest.mark.parametrize(
    ("error", "status_code", "body"),
    [
        (MetadataCatalogUnavailableError("catalog read failed"), 503, GENERIC_503),
        (RuntimeError("failed"), 500, GENERIC_500),
    ],
    ids=["503", "500"],
)
def test_a_failing_runtime_leaves_the_answer_unchanged(
    monkeypatch, error: BaseException, status_code: int, body: dict[str, str]
) -> None:
    monkeypatch.setattr(observability, "get_runtime", FailingRuntime)

    response = _get(_reader_failing_with(_caused_by(error, _lost_connection())))

    assert (response.status_code, response.json()) == (status_code, body)


def test_a_cause_chain_that_loops_back_names_each_error_once() -> None:
    first = RuntimeError("first")
    second = ValueError("second")
    first.__cause__ = second
    second.__cause__ = first

    attributes = read_failure_attributes(first, 500, "v2_metadata_query_failed")

    assert attributes["error.cause_types"] == "builtins.ValueError"


def test_a_long_cause_chain_names_its_first_errors_only() -> None:
    error = RuntimeError("outermost")
    current = error
    for _depth in range(MAX_NAMED_CAUSES + 2):
        cause = KeyError("cause")
        current.__cause__ = cause
        current = cause

    attributes = read_failure_attributes(error, 500, "v2_metadata_query_failed")

    assert attributes["error.cause_types"] == ", ".join(
        ["builtins.KeyError"] * MAX_NAMED_CAUSES
    )
