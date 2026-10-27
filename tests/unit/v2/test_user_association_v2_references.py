"""Saved reports and simulations that name v2 records, checked with the entrypoint.

The v2 tables keep no foreign key to the Simulation Entrypoint's reports and
simulations, so each v2 ID is checked with the entrypoint before it is saved.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlmodel import select

from policyengine_api.data.v2.models import (
    UserReportAssociation,
    UserSimulationAssociation,
)
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
from policyengine_api.services.v2.user_simulations.database_session import (
    UserSimulationDatabaseSession,
)
from policyengine_api.services.v2.user_simulations.services import (
    V2UserSimulationService,
)
from policyengine_api.services.v2.user_simulations.types import (
    UserSimulationCreateFields,
    UserSimulationUpdateInput,
)
from tests.unit.v2.economy_report_support import (
    BASELINE_SIMULATION_ID,
    REPORT_ID,
    FakeEconomyReportSimulation,
    report_record,
    simulation_record,
)
from tests.unit.v2.user_service_support import (
    ALICE,
    default_legacy_references,
    v2_store,
)

OTHER_REPORT_ID = UUID("00000000-0000-4000-8000-000000000199")
UK_SIMULATION_ID = UUID("00000000-0000-4000-8000-000000000196")


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


@pytest.fixture
def simulation_entrypoint() -> FakeEconomyReportSimulation:
    entrypoint = FakeEconomyReportSimulation()
    entrypoint.simulations = {
        BASELINE_SIMULATION_ID: simulation_record(BASELINE_SIMULATION_ID),
        UK_SIMULATION_ID: simulation_record(UK_SIMULATION_ID, country_id="uk"),
    }
    return entrypoint


def _simulation_service(store, entrypoint) -> V2UserSimulationService:
    return V2UserSimulationService(
        UserSimulationDatabaseSession(store.sessions),
        default_legacy_references(),
        SimulationReferenceService(entrypoint),
    )


def _saved_simulations(store) -> list[UserSimulationAssociation]:
    with store.sessions() as session:
        return list(session.exec(select(UserSimulationAssociation)).all())


def test_a_simulation_of_the_country_is_saved_by_its_v2_id(
    store, simulation_entrypoint
) -> None:
    saved = _simulation_service(store, simulation_entrypoint).create_user_simulation(
        principal=ALICE,
        association_input=UserSimulationCreateFields(
            country_id="us", simulation_id=BASELINE_SIMULATION_ID
        ),
    )

    assert saved.simulation_id == BASELINE_SIMULATION_ID
    assert saved.legacy_simulation_id is None
    assert simulation_entrypoint.calls == [("get_simulation", BASELINE_SIMULATION_ID)]


@pytest.mark.parametrize(
    "simulation_id",
    [UK_SIMULATION_ID, UUID("00000000-0000-4000-8000-000000000197")],
    ids=["other-country", "unknown"],
)
def test_a_simulation_the_entrypoint_lacks_in_the_country_is_not_saved(
    store, simulation_entrypoint, simulation_id
) -> None:
    with pytest.raises(SimulationReferenceNotFoundError) as raised:
        _simulation_service(store, simulation_entrypoint).create_user_simulation(
            principal=ALICE,
            association_input=UserSimulationCreateFields(
                country_id="us", simulation_id=simulation_id
            ),
        )

    assert str(raised.value) == (
        f"v2 simulation {simulation_id} was not found for country us"
    )
    assert _saved_simulations(store) == []


def test_a_saved_simulation_is_repointed_to_a_checked_v2_simulation(
    store, simulation_entrypoint
) -> None:
    service = _simulation_service(store, simulation_entrypoint)
    saved = service.create_user_simulation(
        principal=ALICE,
        association_input=UserSimulationCreateFields(
            country_id="us", legacy_simulation_id=613
        ),
    )

    repointed = service.patch_user_simulation(
        principal=ALICE,
        country_id="us",
        association_id=saved.id,
        association_input=UserSimulationUpdateInput(
            simulation_id=BASELINE_SIMULATION_ID
        ),
    )
    with pytest.raises(SimulationReferenceNotFoundError):
        service.patch_user_simulation(
            principal=ALICE,
            country_id="us",
            association_id=saved.id,
            association_input=UserSimulationUpdateInput(simulation_id=UK_SIMULATION_ID),
        )

    assert (repointed.simulation_id, repointed.legacy_simulation_id) == (
        BASELINE_SIMULATION_ID,
        613,
    )


def test_a_saved_simulation_needs_a_simulation_reference() -> None:
    with pytest.raises(ValidationError):
        UserSimulationCreateFields(country_id="us")
    with pytest.raises(ValidationError):
        UserSimulationUpdateInput(simulation_id=None)
