"""Saved reports and simulations that name v2 records, checked with the entrypoint.

The v2 tables keep no foreign key to the Simulation Entrypoint's reports and
simulations, so each v2 ID is checked with the entrypoint before it is saved.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlmodel import select

from policyengine_api.data.v2.models import UserReportAssociation
from policyengine_api.services.v2.economy_reports.types import (
    SimulationServiceUnavailableError,
)
from policyengine_api.services.v2.legacy_refs.validators import (
    LegacyReferenceNotFoundError,
)
from policyengine_api.services.v2.simulation_refs.services import (
    SimulationReferenceService,
)
from policyengine_api.services.v2.simulation_refs.validators import (
    SimulationReferenceNotFoundError,
)
from policyengine_api.services.v2.user_reports.database_session import (
    UserReportDatabaseSession,
)
from policyengine_api.services.v2.user_reports.services import V2UserReportService
from policyengine_api.services.v2.user_reports.types import (
    UserReportCreateFields,
    UserReportUpdateInput,
)
from tests.unit.v2.economy_report_support import (
    REPORT_ID,
    FakeEconomyReportSimulation,
    report_record,
)
from tests.unit.v2.user_service_support import (
    ALICE,
    default_legacy_references,
    v2_store,
)

OTHER_REPORT_ID = UUID("00000000-0000-4000-8000-000000000199")


@pytest.fixture
def entrypoint() -> FakeEconomyReportSimulation:
    return FakeEconomyReportSimulation(
        report_record(),
        report_record(report_id=OTHER_REPORT_ID, country_id="uk"),
    )


@pytest.fixture
def store():
    with v2_store() as v2:
        yield v2


def _service(store, entrypoint) -> V2UserReportService:
    return V2UserReportService(
        UserReportDatabaseSession(store.sessions),
        default_legacy_references(),
        SimulationReferenceService(entrypoint),
    )


def _saved_reports(store) -> list[UserReportAssociation]:
    with store.sessions() as session:
        return list(session.exec(select(UserReportAssociation)).all())


def test_a_report_of_the_country_is_saved_by_its_v2_id(store, entrypoint) -> None:
    saved = _service(store, entrypoint).create_user_report(
        principal=ALICE,
        association_input=UserReportCreateFields(country_id="us", report_id=REPORT_ID),
    )

    assert saved.report_id == REPORT_ID
    assert saved.legacy_report_id is None
    assert entrypoint.calls == [("get_report", REPORT_ID)]


@pytest.mark.parametrize(
    "report_id",
    [OTHER_REPORT_ID, UUID("00000000-0000-4000-8000-000000000198")],
    ids=["other-country", "unknown"],
)
def test_a_report_the_entrypoint_lacks_in_the_country_is_not_saved(
    store, entrypoint, report_id
) -> None:
    with pytest.raises(SimulationReferenceNotFoundError) as raised:
        _service(store, entrypoint).create_user_report(
            principal=ALICE,
            association_input=UserReportCreateFields(
                country_id="us", report_id=report_id
            ),
        )

    assert str(raised.value) == (f"v2 report {report_id} was not found for country us")
    assert _saved_reports(store) == []


def test_both_references_are_checked_before_saving(store, entrypoint) -> None:
    service = _service(store, entrypoint)

    saved = service.create_user_report(
        principal=ALICE,
        association_input=UserReportCreateFields(
            country_id="us", report_id=REPORT_ID, legacy_report_id=615
        ),
    )
    with pytest.raises(LegacyReferenceNotFoundError):
        service.create_user_report(
            principal=ALICE,
            association_input=UserReportCreateFields(
                country_id="us", report_id=REPORT_ID, legacy_report_id=999
            ),
        )

    assert (saved.report_id, saved.legacy_report_id) == (REPORT_ID, 615)
    assert len(_saved_reports(store)) == 1


def test_a_saved_report_is_repointed_to_a_checked_v2_report(store, entrypoint) -> None:
    service = _service(store, entrypoint)
    saved = service.create_user_report(
        principal=ALICE,
        association_input=UserReportCreateFields(country_id="us", legacy_report_id=615),
    )

    repointed = service.patch_user_report(
        principal=ALICE,
        country_id="us",
        association_id=saved.id,
        association_input=UserReportUpdateInput(report_id=REPORT_ID),
    )
    with pytest.raises(SimulationReferenceNotFoundError):
        service.patch_user_report(
            principal=ALICE,
            country_id="us",
            association_id=saved.id,
            association_input=UserReportUpdateInput(report_id=OTHER_REPORT_ID),
        )

    assert (repointed.report_id, repointed.legacy_report_id) == (REPORT_ID, 615)
    assert _saved_reports(store)[0].report_id == REPORT_ID


def test_a_v2_report_cannot_be_saved_while_the_entrypoint_is_unavailable(
    store, entrypoint
) -> None:
    entrypoint.error = SimulationServiceUnavailableError("HTTP 503")

    with pytest.raises(SimulationServiceUnavailableError):
        _service(store, entrypoint).create_user_report(
            principal=ALICE,
            association_input=UserReportCreateFields(
                country_id="us", report_id=REPORT_ID
            ),
        )

    assert _saved_reports(store) == []


def test_a_v2_report_cannot_be_saved_without_the_entrypoint_check(store) -> None:
    service = V2UserReportService(
        UserReportDatabaseSession(store.sessions), default_legacy_references()
    )

    with pytest.raises(SimulationServiceUnavailableError):
        service.create_user_report(
            principal=ALICE,
            association_input=UserReportCreateFields(
                country_id="us", report_id=REPORT_ID
            ),
        )


def test_a_saved_report_needs_a_report_reference() -> None:
    with pytest.raises(ValidationError):
        UserReportCreateFields(country_id="us")
    with pytest.raises(ValidationError):
        UserReportUpdateInput(report_id=None)


def test_a_shared_report_shows_its_v2_report(store, entrypoint) -> None:
    service = _service(store, entrypoint)
    saved = service.create_user_report(
        principal=ALICE,
        association_input=UserReportCreateFields(country_id="us", report_id=REPORT_ID),
    )

    shared = service.get_shared_user_report(country_id="us", association_id=saved.id)

    assert shared.report_id == REPORT_ID
