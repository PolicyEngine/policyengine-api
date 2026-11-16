"""Runtime events for v2 metadata reads that fail with a generic 503 or a 500.

The response stays the generic one, but the observability runtime records one
event that says what failed: the route and request ID, which the runtime takes
from the request it is serving, then the response status, the caught error's
class, the class of each error in its ``__cause__`` chain, the driver's
SQLSTATE and whether SQLAlchemy found the connection lost. It never records an
error's message, which can carry the SQL statement, its parameters, host
names, addresses or credentials. These tests serve the request through a runtime
configured as the process's is, but writing its records to a list, so they see
the event exactly as the runtime writes it, request context included.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from policyengine_observability import (
    CustomLogDestination,
    LoggingConfig,
    ObservabilityConfig,
    configure,
)
from sqlalchemy.exc import OperationalError

from policyengine_api import observability
from policyengine_api.data.v2.catalog.catalog_selection_validation import (
    MetadataCatalogUnavailableError,
)
from policyengine_api.observability_identity import (
    deployment_identity,
    service_identity,
)
from policyengine_api.services.v2.metadata.validators import (
    CatalogValuesPrunedError,
)
from tests.fixtures.v2_metadata_routes import ResourceReader, metadata_route_client

if TYPE_CHECKING:
    from collections.abc import Iterator

    from policyengine_observability import ObservabilityRuntime

ROUTE = "/v2/parameter-values"
PATH = f"{ROUTE}?country_id=us&limit=1"
FAILURE_EVENT = "v2_metadata_read_failed"
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


class DriverAdminShutdownError(Exception):
    """Stands in for psycopg's error for SQLSTATE 57P01, a terminated connection."""

    sqlstate = "57P01"


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
    """Serve requests through a runtime whose records the test can read."""
    record_list = RecordList()
    runtime = configure(
        ObservabilityConfig.from_env(
            service=service_identity(),
            deployment=deployment_identity(),
            logging=LoggingConfig(
                destinations=(
                    CustomLogDestination(
                        name="test-records",
                        writer_factory=lambda: record_list,
                        delivery="inline",
                    ),
                ),
            ),
        )
    )
    monkeypatch.setattr(observability, "get_runtime", lambda: runtime)
    try:
        yield record_list, runtime
    finally:
        runtime.shutdown()


def _get(reader: ResourceReader, runtime: ObservabilityRuntime):
    client = metadata_route_client(lambda: reader, observability_runtime=runtime)
    return client.get(PATH)


def _qualified_name(error_class: type[BaseException]) -> str:
    return f"{error_class.__module__}.{error_class.__qualname__}"


def _lost_connection() -> OperationalError:
    """Return SQLAlchemy's error for a connection lost mid-query, as psycopg raises it.

    Every message in the chain names the statement, a parameter, the pooler's
    host and address and a password, as a driver's message can.
    """
    driver_error = DriverAdminShutdownError(
        "terminating connection due to administrator command: "
        "postgresql://reader:hunter2@pooler.example.internal (10.12.0.7)"
    )
    database_error = OperationalError(
        STATEMENT, {"c": PARAMETER_VALUE}, driver_error, connection_invalidated=True
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
    error = _caused_by(
        MetadataCatalogUnavailableError(f"catalog read failed: {STATEMENT}"),
        _lost_connection(),
    )
    reader = ResourceReader({"list_parameter_values": None}, error=error)

    record_list, runtime = recorded

    response = _get(reader, runtime)
    [record] = record_list.failures()

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "message": "V2 metadata catalog is unavailable",
    }
    assert record["severity"] == "ERROR"
    assert record["http.route"] == ROUTE
    assert record["request.id"] == response.headers["x-policyengine-request-id"]
    assert record["attributes"] == {
        "http.response.status_code": 503,
        "error.type": _qualified_name(MetadataCatalogUnavailableError),
        "error.cause_types": (
            "sqlalchemy.exc.OperationalError, "
            f"{_qualified_name(DriverAdminShutdownError)}"
        ),
        "database.sqlstate": "57P01",
        "database.connection_invalidated": True,
    }
    _assert_nothing_sensitive(record)


def test_an_unexpected_failure_answers_the_same_500_and_records_its_cause(
    recorded,
) -> None:
    error = _caused_by(RuntimeError(f"failed on {STATEMENT}"), _lost_connection())
    reader = ResourceReader({"list_parameter_values": None}, error=error)

    record_list, runtime = recorded

    response = _get(reader, runtime)
    [record] = record_list.failures()

    assert response.status_code == 500
    assert response.json() == {"status": "error", "message": "V2 metadata query failed"}
    assert (record["severity"], record["http.route"]) == ("ERROR", ROUTE)
    assert record["attributes"] == {
        "http.response.status_code": 500,
        "error.type": "builtins.RuntimeError",
        "error.cause_types": (
            "sqlalchemy.exc.OperationalError, "
            f"{_qualified_name(DriverAdminShutdownError)}"
        ),
        "database.sqlstate": "57P01",
        "database.connection_invalidated": True,
    }
    _assert_nothing_sensitive(record)


def test_a_failure_without_a_database_cause_records_only_its_class(
    recorded,
) -> None:
    reader = ResourceReader(
        {"list_parameter_values": None},
        error=MetadataCatalogUnavailableError("catalog connection refused"),
    )

    record_list, runtime = recorded

    response = _get(reader, runtime)
    [record] = record_list.failures()

    assert response.status_code == 503
    assert record["attributes"] == {
        "http.response.status_code": 503,
        "error.type": _qualified_name(MetadataCatalogUnavailableError),
    }


def test_a_pruned_version_answer_records_no_failure(recorded) -> None:
    reader = ResourceReader(
        {"list_parameter_values": None},
        error=CatalogValuesPrunedError("pruned", running_version=True),
    )

    record_list, runtime = recorded

    response = _get(reader, runtime)

    assert response.status_code == 503
    assert record_list.failures() == []


def test_a_failing_runtime_leaves_the_503_unchanged(monkeypatch) -> None:
    monkeypatch.setattr(observability, "get_runtime", FailingRuntime)
    error = _caused_by(
        MetadataCatalogUnavailableError("catalog read failed"), _lost_connection()
    )
    reader = ResourceReader({"list_parameter_values": None}, error=error)

    response = metadata_route_client(lambda: reader).get(PATH)

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "message": "V2 metadata catalog is unavailable",
    }
