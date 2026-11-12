"""Saved reports and simulations name a detailed-save record or a v1 one."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from policyengine_api.data.v2.models import (
    UserReportAssociation,
    UserSimulationAssociation,
)
from policyengine_api.services.v2.associations.validators import (
    AssociationReferenceConflictError,
    require_one_reference,
    violates_foreign_key,
)
from policyengine_api.services.v2.user_reports.database_connectors.creates import (
    create_user_report,
)
from policyengine_api.services.v2.user_reports.database_connectors.updates import (
    update_user_report,
)
from policyengine_api.services.v2.user_reports.types import (
    UserReportCreateFields,
    UserReportCreationInput,
    UserReportUpdateInput,
)
from policyengine_api.services.v2.user_reports.validators import (
    AssociationReportNotFoundError,
)
from policyengine_api.services.v2.user_simulations.database_connectors.creates import (
    create_user_simulation,
)
from policyengine_api.services.v2.user_simulations.database_connectors.updates import (
    update_user_simulation,
)
from policyengine_api.services.v2.user_simulations.types import (
    UserSimulationCreateFields,
    UserSimulationCreationInput,
    UserSimulationUpdateInput,
)
from policyengine_api.services.v2.user_simulations.validators import (
    AssociationSimulationNotFoundError,
)
from tests.unit.v2.user_route_support import user_route_client

if TYPE_CHECKING:
    from uuid import UUID

    from sqlmodel import Session

REPORT_KEY = "fk_user_report_associations_report_id_reports"
SIMULATION_KEY = "fk_user_simulation_associations_simulation_id_simulations"
# Another foreign key of the same rows, which the write's checks don't cover.
SAVED_REPORT_OWNER_KEY = "fk_user_report_associations_user_id_users"
SAVED_SIMULATION_OWNER_KEY = "fk_user_simulation_associations_user_id_users"


def integrity_error(sqlstate: str, constraint_name: str | None) -> IntegrityError:
    """Return an IntegrityError as psycopg reports one, with its SQLSTATE."""
    driver_error = SimpleNamespace(
        sqlstate=sqlstate, diag=SimpleNamespace(constraint_name=constraint_name)
    )
    return IntegrityError("INSERT", {}, driver_error)


def test_a_saved_report_names_a_detailed_save_report_or_a_v1_report() -> None:
    report_id = uuid4()

    by_report = UserReportCreateFields(country_id="us", report_id=report_id)
    by_number = UserReportCreateFields(country_id="us", legacy_report_id=615)

    assert (by_report.report_id, by_report.legacy_report_id) == (report_id, None)
    assert (by_number.report_id, by_number.legacy_report_id) == (None, 615)
    with pytest.raises(ValidationError, match="report_id or legacy_report_id"):
        UserReportCreateFields(country_id="us")


def test_a_saved_simulation_names_a_detailed_save_simulation_or_a_v1_one() -> None:
    simulation_id = uuid4()

    saved = UserSimulationCreateFields(country_id="uk", simulation_id=simulation_id)

    assert saved.simulation_id == simulation_id
    assert saved.legacy_simulation_id is None
    with pytest.raises(ValidationError, match="simulation_id or legacy_simulation_id"):
        UserSimulationCreateFields(country_id="uk")


@pytest.mark.parametrize(
    ("model", "field"),
    [
        (UserReportUpdateInput, "report_id"),
        (UserSimulationUpdateInput, "simulation_id"),
    ],
    ids=["report", "simulation"],
)
def test_a_detailed_save_reference_cannot_be_cleared(model: type, field: str) -> None:
    with pytest.raises(ValidationError, match=f"{field} must not be null"):
        model(**{field: None})


def test_naming_both_references_is_a_conflict() -> None:
    with pytest.raises(AssociationReferenceConflictError, match="not both"):
        require_one_reference("report", detailed_save_id=uuid4(), legacy_id=615)
    require_one_reference("report", detailed_save_id=uuid4(), legacy_id=None)
    require_one_reference("report", detailed_save_id=None, legacy_id=615)


def test_only_the_named_foreign_key_violation_counts() -> None:
    assert violates_foreign_key(integrity_error("23503", REPORT_KEY), REPORT_KEY)
    assert not violates_foreign_key(
        integrity_error("23503", "fk_user_report_associations_user_id_users"),
        REPORT_KEY,
    )
    assert not violates_foreign_key(integrity_error("23505", REPORT_KEY), REPORT_KEY)


class RefusingFlushSession:
    """A session whose flush fails with ``error``, as PostgreSQL refusing a write."""

    def __init__(self, error: IntegrityError) -> None:
        self.error = error

    def add(self, _row: object) -> None:
        """Accept the row; the database refuses it at flush."""

    def flush(self) -> None:
        raise self.error

    def refresh(self, _row: object) -> None:
        msg = "a refused write is never read back"
        raise AssertionError(msg)


def refusing_session(sqlstate: str, constraint_name: str) -> Session:
    """Return a session whose flush fails with that SQLSTATE on that constraint."""
    return cast(
        "Session", RefusingFlushSession(integrity_error(sqlstate, constraint_name))
    )


def save_report(session: Session, *, operation: str, report_id: UUID) -> None:
    """Save a new report naming ``report_id``, or repoint a saved one to it."""
    if operation == "create":
        create_user_report(
            session,
            UserReportCreationInput(
                country_id="us", user_id=uuid4(), report_id=report_id
            ),
        )
        return
    saved = UserReportAssociation(user_id=uuid4(), country_id="us", report_id=uuid4())
    update_user_report(session, saved, {"report_id": report_id})


def save_simulation(session: Session, *, operation: str, simulation_id: UUID) -> None:
    """Save a new simulation naming ``simulation_id``, or repoint a saved one."""
    if operation == "create":
        create_user_simulation(
            session,
            UserSimulationCreationInput(
                country_id="uk", user_id=uuid4(), simulation_id=simulation_id
            ),
        )
        return
    saved = UserSimulationAssociation(
        user_id=uuid4(), country_id="uk", simulation_id=uuid4()
    )
    update_user_simulation(
        session, saved, UserSimulationUpdateInput(simulation_id=simulation_id)
    )


@pytest.mark.parametrize("operation", ["create", "update"])
def test_a_report_deleted_before_the_saved_report_is_written_is_not_found(
    operation: str,
) -> None:
    report_id = uuid4()

    with pytest.raises(
        AssociationReportNotFoundError,
        match=f"Report {report_id} was not found in country 'us'",
    ) as raised:
        save_report(
            refusing_session("23503", REPORT_KEY),
            operation=operation,
            report_id=report_id,
        )

    assert isinstance(raised.value.__cause__, IntegrityError)


@pytest.mark.parametrize("operation", ["create", "update"])
def test_a_simulation_deleted_before_the_saved_one_is_written_is_not_found(
    operation: str,
) -> None:
    simulation_id = uuid4()

    with pytest.raises(
        AssociationSimulationNotFoundError,
        match=f"Simulation {simulation_id} was not found in country 'uk'",
    ) as raised:
        save_simulation(
            refusing_session("23503", SIMULATION_KEY),
            operation=operation,
            simulation_id=simulation_id,
        )

    assert isinstance(raised.value.__cause__, IntegrityError)


@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.parametrize(
    ("sqlstate", "constraint_name"),
    [("23503", SAVED_REPORT_OWNER_KEY), ("23505", REPORT_KEY)],
    ids=["owner-key", "not-a-foreign-key-violation"],
)
def test_a_saved_reports_other_integrity_errors_are_raised_unchanged(
    operation: str, sqlstate: str, constraint_name: str
) -> None:
    with pytest.raises(IntegrityError):
        save_report(
            refusing_session(sqlstate, constraint_name),
            operation=operation,
            report_id=uuid4(),
        )


@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.parametrize(
    ("sqlstate", "constraint_name"),
    [("23503", SAVED_SIMULATION_OWNER_KEY), ("23505", SIMULATION_KEY)],
    ids=["owner-key", "not-a-foreign-key-violation"],
)
def test_a_saved_simulations_other_integrity_errors_are_raised_unchanged(
    operation: str, sqlstate: str, constraint_name: str
) -> None:
    with pytest.raises(IntegrityError):
        save_simulation(
            refusing_session(sqlstate, constraint_name),
            operation=operation,
            simulation_id=uuid4(),
        )


class RefusingReports:
    """A saved-report service that raises ``error`` on create."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    def create_user_report(self, **_arguments: object) -> object:
        raise self.error


class RefusingSimulations:
    """A saved-simulation service that raises ``error`` on create."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    def create_user_simulation(self, **_arguments: object) -> object:
        raise self.error


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (AssociationReportNotFoundError("Report r was not found in 'us'"), 404),
        (AssociationReferenceConflictError("not both"), 400),
    ],
    ids=["missing-report", "both-references"],
)
def test_saved_report_reference_failures_answer_their_status(
    error: Exception, status_code: int
) -> None:
    client, _flask_calls = user_route_client(
        v2_user_report_service_factory=lambda: RefusingReports(error)
    )

    response = client.post(
        "/v2/user-reports?country_id=us",
        json={"country_id": "us", "report_id": str(uuid4())},
    )

    assert response.status_code == status_code
    assert response.json() == {"status": "error", "message": str(error)}


def test_a_saved_simulation_naming_a_missing_simulation_is_not_found() -> None:
    error = AssociationSimulationNotFoundError("Simulation s was not found")
    client, _flask_calls = user_route_client(
        v2_user_simulation_service_factory=lambda: RefusingSimulations(error)
    )

    response = client.post(
        "/v2/user-simulations?country_id=us",
        json={"country_id": "us", "simulation_id": str(uuid4())},
    )

    assert response.status_code == 404
    assert response.json()["message"] == str(error)
