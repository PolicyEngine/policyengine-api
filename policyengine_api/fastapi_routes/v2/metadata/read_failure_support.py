"""Record why a v2 metadata read answered the generic 503 or a 500.

A catalog the API can't read answers the generic 503 "V2 metadata catalog is
unavailable", and any other unexpected failure the 500 "V2 metadata query
failed", so the response names no cause. Each such answer records one runtime
event, ``v2_metadata_read_failed``, at ERROR. The runtime adds the request it
is serving: its ID, method and matched route. The event adds:

- ``http.response.status_code``: 503 or 500;
- ``error_type``: the caught error's class, as ``module.QualifiedName``;
- ``failure_category``: ``v2_metadata_catalog_unavailable`` for the 503 or
  ``v2_metadata_query_failed`` for the 500. The scheduled error-issue job
  groups such an event by its route, ``error_type`` and ``failure_category``,
  the keys the API's other events use;
- ``error.cause_types``: the class of each error in its ``__cause__`` chain,
  outermost first and joined by ", ", or absent when it has no cause;
- ``database.sqlstate``: the first SQLSTATE an error in the chain carries, as
  psycopg's errors do in ``sqlstate``;
- ``database.connection_invalidated``: whether SQLAlchemy found the connection
  lost, from the first error in the chain with ``connection_invalidated``, as
  ``sqlalchemy.exc.DBAPIError`` has.

It records no error message: SQLAlchemy's and the driver's messages carry the
SQL statement and its parameters, and can carry host names, addresses and
credentials. The attributes are read by name, so this module imports neither
SQLAlchemy nor a driver. Recording never changes the response.
"""

from __future__ import annotations

import contextlib

METADATA_READ_FAILURE_EVENT = "v2_metadata_read_failed"
CATALOG_UNAVAILABLE_FAILURE = "v2_metadata_catalog_unavailable"
QUERY_FAILED_FAILURE = "v2_metadata_query_failed"
MAX_NAMED_CAUSES = 10
"""How many errors of a ``__cause__`` chain the event names at most."""


def record_metadata_read_failure(
    error: BaseException, status_code: int, failure_category: str
) -> None:
    """Record why one metadata read failed; recording never fails the request."""
    # Telemetry must never change a metadata response.
    with contextlib.suppress(Exception):
        from policyengine_api import (  # noqa: PLC0415  # importing it builds the process-wide runtime, which importing the route modules alone must not
            observability,
        )

        observability.get_runtime().event(
            METADATA_READ_FAILURE_EVENT,
            severity="ERROR",
            attributes=read_failure_attributes(error, status_code, failure_category),
        )


def read_failure_attributes(
    error: BaseException, status_code: int, failure_category: str
) -> dict[str, str | int | bool]:
    """Return the event's attributes: class names, SQLSTATE and lost-connection flag."""
    causes = _cause_chain(error)
    attributes: dict[str, str | int | bool] = {
        "http.response.status_code": status_code,
        "error_type": _class_name(error),
        "failure_category": failure_category,
    }
    if causes:
        attributes["error.cause_types"] = ", ".join(
            _class_name(cause) for cause in causes
        )
    chain = (error, *causes)
    sqlstate = next(
        (
            code
            for code in (getattr(item, "sqlstate", None) for item in chain)
            if isinstance(code, str) and code
        ),
        None,
    )
    if sqlstate is not None:
        attributes["database.sqlstate"] = sqlstate
    invalidated = next(
        (
            flag
            for flag in (
                getattr(item, "connection_invalidated", None) for item in chain
            )
            if isinstance(flag, bool)
        ),
        None,
    )
    if invalidated is not None:
        attributes["database.connection_invalidated"] = invalidated
    return attributes


def _cause_chain(error: BaseException) -> list[BaseException]:
    causes: list[BaseException] = []
    cause = error.__cause__
    while cause is not None and cause is not error and len(causes) < MAX_NAMED_CAUSES:
        if cause in causes:
            break
        causes.append(cause)
        cause = cause.__cause__
    return causes


def _class_name(error: BaseException) -> str:
    error_class = type(error)
    return f"{error_class.__module__}.{error_class.__qualname__}"
