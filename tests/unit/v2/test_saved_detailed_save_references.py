"""Saved reports and simulations name a detailed-save record or a v1 one."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from policyengine_api.services.v2.associations.validators import (
    AssociationReferenceConflictError,
    require_one_reference,
    violates_foreign_key,
)
from policyengine_api.services.v2.user_reports.types import (
    UserReportCreateFields,
    UserReportUpdateInput,
)
from policyengine_api.services.v2.user_reports.validators import (
    AssociationReportNotFoundError,
)
from policyengine_api.services.v2.user_simulations.types import (
    UserSimulationCreateFields,
    UserSimulationUpdateInput,
)
from policyengine_api.services.v2.user_simulations.validators import (
    AssociationSimulationNotFoundError,
)
from tests.unit.v2.user_route_support import user_route_client

REPORT_KEY = "fk_user_report_associations_report_id_reports"


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
