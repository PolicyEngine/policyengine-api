"""Save detailed-save reports and simulations in migrated PostgreSQL.

The saved-record services run as the Public API's runtime role. A saved
report or simulation names a stored record of its country, checked with a
SELECT in the write's own transaction; the database's ``RESTRICT`` foreign
keys refuse one deleted between the check and the write, which is answered
as not found too. A request naming both a detailed-save ID and a v1 number
is refused.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from sqlmodel import Session

from policyengine_api.constants import REPO
from policyengine_api.data.v2.models import User
from policyengine_api.services.v2.associations.validators import (
    AssociationReferenceConflictError,
)
from policyengine_api.services.v2.identity.types import UnauthenticatedPrincipal
from policyengine_api.services.v2.user_reports import services as report_services
from policyengine_api.services.v2.user_reports.database_session import (
    UserReportDatabaseSession,
)
from policyengine_api.services.v2.user_reports.services import V2UserReportService
from policyengine_api.services.v2.user_reports.types import (
    UserReportCreateFields,
    UserReportUpdateInput,
)
from policyengine_api.services.v2.user_reports.validators import (
    AssociationReportNotFoundError,
)
from policyengine_api.services.v2.user_simulations import (
    services as simulation_services,
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
from policyengine_api.services.v2.user_simulations.validators import (
    AssociationSimulationNotFoundError,
)
from tests.integration.stored_report_rows import (
    delete_catalog,
    store_catalog,
    store_report,
    store_simulation,
)
from tests.unit.v2.user_service_support import default_legacy_references

if TYPE_CHECKING:
    from collections.abc import Iterator
    from uuid import UUID

    from sqlalchemy import Engine

    from tests.integration.stored_report_rows import CatalogRows


@pytest.fixture
def owner_engine(disposable_v2_database_url: str) -> Iterator[Engine]:
    command.upgrade(Config(str(REPO / "alembic-v2.ini")), "head")
    engine = create_engine(disposable_v2_database_url, poolclass=NullPool)
    yield engine
    engine.dispose()


@pytest.fixture
def browsers(owner_engine: Engine) -> Iterator[list[UUID]]:
    """Signed-out browsers' user IDs; their users and saved records go afterwards."""
    user_ids: list[UUID] = []
    yield user_ids
    with owner_engine.begin() as connection:
        connection.execute(delete(User).where(User.id.in_(user_ids)))


@pytest.fixture
def catalogs(
    owner_engine: Engine, browsers: list[UUID]
) -> Iterator[dict[str, CatalogRows]]:
    """Store a US and a UK catalog; delete them after the records that name them."""
    with owner_engine.begin() as connection:
        stored = {
            country: store_catalog(connection, country) for country in ("us", "uk")
        }
    yield stored
    with owner_engine.begin() as connection:
        connection.execute(delete(User).where(User.id.in_(browsers)))
        for catalog in stored.values():
            delete_catalog(connection, catalog)


@pytest.fixture
def runtime_sessions(managed_v2_roles, v2_engine_as_role) -> Iterator[sessionmaker]:
    engine = v2_engine_as_role(managed_v2_roles.runtime, poolclass=NullPool)
    yield sessionmaker(engine, class_=Session, expire_on_commit=False)
    engine.dispose()


def browser(browsers: list[UUID]) -> UnauthenticatedPrincipal:
    user_id = uuid4()
    browsers.append(user_id)
    return UnauthenticatedPrincipal(user_id=user_id)


def report_service(sessions: sessionmaker) -> V2UserReportService:
    return V2UserReportService(
        UserReportDatabaseSession(sessions), default_legacy_references()
    )


def simulation_service(sessions: sessionmaker) -> V2UserSimulationService:
    return V2UserSimulationService(
        UserSimulationDatabaseSession(sessions), default_legacy_references()
    )


def test_a_saved_report_names_a_stored_report_of_its_country(
    owner_engine: Engine,
    catalogs: dict[str, CatalogRows],
    browsers: list[UUID],
    runtime_sessions: sessionmaker,
) -> None:
    with owner_engine.begin() as connection:
        report = store_report(connection, catalogs["us"])
    service = report_service(runtime_sessions)

    saved = service.create_user_report(
        principal=browser(browsers),
        association_input=UserReportCreateFields(
            country_id="us", report_id=report.report_id, name="My reform"
        ),
    )
    shared = service.get_shared_user_report(country_id="us", association_id=saved.id)

    assert saved.report_id == report.report_id
    assert saved.legacy_report_id is None
    assert shared.report_id == report.report_id


def test_a_saved_report_naming_a_missing_or_foreign_report_is_not_found(
    owner_engine: Engine,
    catalogs: dict[str, CatalogRows],
    browsers: list[UUID],
    runtime_sessions: sessionmaker,
) -> None:
    with owner_engine.begin() as connection:
        uk_report = store_report(connection, catalogs["uk"])
    service = report_service(runtime_sessions)
    principal = browser(browsers)

    for report_id in (uuid4(), uk_report.report_id):
        with pytest.raises(AssociationReportNotFoundError, match=str(report_id)):
            service.create_user_report(
                principal=principal,
                association_input=UserReportCreateFields(
                    country_id="us", report_id=report_id
                ),
            )


def test_a_saved_report_naming_both_references_is_refused(
    owner_engine: Engine,
    catalogs: dict[str, CatalogRows],
    browsers: list[UUID],
    runtime_sessions: sessionmaker,
) -> None:
    with owner_engine.begin() as connection:
        report = store_report(connection, catalogs["us"])

    with pytest.raises(AssociationReferenceConflictError, match="not both"):
        report_service(runtime_sessions).create_user_report(
            principal=browser(browsers),
            association_input=UserReportCreateFields(
                country_id="us", report_id=report.report_id, legacy_report_id=615
            ),
        )


def test_a_saved_report_cannot_come_to_name_both_references(
    owner_engine: Engine,
    catalogs: dict[str, CatalogRows],
    browsers: list[UUID],
    runtime_sessions: sessionmaker,
) -> None:
    with owner_engine.begin() as connection:
        report = store_report(connection, catalogs["us"])
    service = report_service(runtime_sessions)
    principal = browser(browsers)
    by_number = service.create_user_report(
        principal=principal,
        association_input=UserReportCreateFields(country_id="us", legacy_report_id=615),
    )
    by_report = service.create_user_report(
        principal=principal,
        association_input=UserReportCreateFields(
            country_id="us", report_id=report.report_id
        ),
    )

    for association_id, change in (
        (by_number.id, {"report_id": report.report_id}),
        (by_report.id, {"legacy_report_id": 616}),
        (by_report.id, {"report_id": report.report_id, "legacy_report_id": 616}),
    ):
        with pytest.raises(AssociationReferenceConflictError, match="not both"):
            service.patch_user_report(
                principal=principal,
                country_id="us",
                association_id=association_id,
                association_input=UserReportUpdateInput(**change),
            )


def test_a_saved_report_is_repointed_only_to_a_stored_report(
    owner_engine: Engine,
    catalogs: dict[str, CatalogRows],
    browsers: list[UUID],
    runtime_sessions: sessionmaker,
) -> None:
    with owner_engine.begin() as connection:
        first = store_report(connection, catalogs["us"])
        second = store_report(connection, catalogs["us"])
    service = report_service(runtime_sessions)
    principal = browser(browsers)
    saved = service.create_user_report(
        principal=principal,
        association_input=UserReportCreateFields(
            country_id="us", report_id=first.report_id
        ),
    )

    repointed = service.patch_user_report(
        principal=principal,
        country_id="us",
        association_id=saved.id,
        association_input=UserReportUpdateInput(report_id=second.report_id),
    )
    with pytest.raises(AssociationReportNotFoundError):
        service.patch_user_report(
            principal=principal,
            country_id="us",
            association_id=saved.id,
            association_input=UserReportUpdateInput(report_id=uuid4()),
        )

    assert repointed.report_id == second.report_id


def test_a_report_gone_after_the_check_is_refused_by_its_foreign_key(
    monkeypatch: pytest.MonkeyPatch,
    catalogs: dict[str, CatalogRows],
    browsers: list[UUID],
    runtime_sessions: sessionmaker,
) -> None:
    # As if the report were deleted between the check and the insert.
    monkeypatch.setattr(
        report_services, "read_report_exists", lambda *_args, **_kwargs: True
    )
    missing_report_id = uuid4()

    with pytest.raises(AssociationReportNotFoundError, match=str(missing_report_id)):
        report_service(runtime_sessions).create_user_report(
            principal=browser(browsers),
            association_input=UserReportCreateFields(
                country_id="us", report_id=missing_report_id
            ),
        )


def test_a_report_gone_before_a_repoint_is_refused_by_its_foreign_key(
    monkeypatch: pytest.MonkeyPatch,
    owner_engine: Engine,
    catalogs: dict[str, CatalogRows],
    browsers: list[UUID],
    runtime_sessions: sessionmaker,
) -> None:
    with owner_engine.begin() as connection:
        report = store_report(connection, catalogs["us"])
    service = report_service(runtime_sessions)
    principal = browser(browsers)
    saved = service.create_user_report(
        principal=principal,
        association_input=UserReportCreateFields(
            country_id="us", report_id=report.report_id
        ),
    )
    # As if the new report were deleted between the check and the update.
    monkeypatch.setattr(
        report_services, "read_report_exists", lambda *_args, **_kwargs: True
    )
    missing_report_id = uuid4()

    with pytest.raises(
        AssociationReportNotFoundError,
        match=f"Report {missing_report_id} was not found in country 'us'",
    ):
        service.patch_user_report(
            principal=principal,
            country_id="us",
            association_id=saved.id,
            association_input=UserReportUpdateInput(report_id=missing_report_id),
        )
    assert (
        service.get_shared_user_report(country_id="us", association_id=saved.id)
    ).report_id == report.report_id


def test_a_saved_simulation_names_a_stored_simulation_of_its_country(
    owner_engine: Engine,
    catalogs: dict[str, CatalogRows],
    browsers: list[UUID],
    runtime_sessions: sessionmaker,
) -> None:
    with owner_engine.begin() as connection:
        simulation_id = store_simulation(connection, catalogs["uk"], policy_id=None)
        other_simulation_id = store_simulation(
            connection, catalogs["uk"], policy_id=None
        )
    service = simulation_service(runtime_sessions)
    principal = browser(browsers)

    saved = service.create_user_simulation(
        principal=principal,
        association_input=UserSimulationCreateFields(
            country_id="uk", simulation_id=simulation_id
        ),
    )
    repointed = service.patch_user_simulation(
        principal=principal,
        country_id="uk",
        association_id=saved.id,
        association_input=UserSimulationUpdateInput(simulation_id=other_simulation_id),
    )

    assert saved.simulation_id == simulation_id
    assert saved.legacy_simulation_id is None
    assert repointed.simulation_id == other_simulation_id


def test_a_saved_simulation_of_another_country_or_none_is_not_found(
    owner_engine: Engine,
    catalogs: dict[str, CatalogRows],
    browsers: list[UUID],
    runtime_sessions: sessionmaker,
) -> None:
    with owner_engine.begin() as connection:
        uk_simulation_id = store_simulation(connection, catalogs["uk"], policy_id=None)
    service = simulation_service(runtime_sessions)
    principal = browser(browsers)

    for simulation_id in (uuid4(), uk_simulation_id):
        with pytest.raises(
            AssociationSimulationNotFoundError, match=str(simulation_id)
        ):
            service.create_user_simulation(
                principal=principal,
                association_input=UserSimulationCreateFields(
                    country_id="us", simulation_id=simulation_id
                ),
            )


def test_a_saved_simulation_never_names_both_references(
    owner_engine: Engine,
    catalogs: dict[str, CatalogRows],
    browsers: list[UUID],
    runtime_sessions: sessionmaker,
) -> None:
    with owner_engine.begin() as connection:
        simulation_id = store_simulation(connection, catalogs["us"], policy_id=None)
    service = simulation_service(runtime_sessions)
    principal = browser(browsers)
    by_number = service.create_user_simulation(
        principal=principal,
        association_input=UserSimulationCreateFields(
            country_id="us", legacy_simulation_id=613
        ),
    )

    with pytest.raises(AssociationReferenceConflictError, match="not both"):
        service.create_user_simulation(
            principal=principal,
            association_input=UserSimulationCreateFields(
                country_id="us", simulation_id=simulation_id, legacy_simulation_id=613
            ),
        )
    with pytest.raises(AssociationReferenceConflictError, match="not both"):
        service.patch_user_simulation(
            principal=principal,
            country_id="us",
            association_id=by_number.id,
            association_input=UserSimulationUpdateInput(simulation_id=simulation_id),
        )


def test_a_simulation_gone_after_the_check_is_refused_by_its_foreign_key(
    monkeypatch: pytest.MonkeyPatch,
    catalogs: dict[str, CatalogRows],
    browsers: list[UUID],
    runtime_sessions: sessionmaker,
) -> None:
    monkeypatch.setattr(
        simulation_services,
        "read_simulation_exists",
        lambda *_args, **_kwargs: True,
    )
    missing_simulation_id = uuid4()

    with pytest.raises(
        AssociationSimulationNotFoundError, match=str(missing_simulation_id)
    ):
        simulation_service(runtime_sessions).create_user_simulation(
            principal=browser(browsers),
            association_input=UserSimulationCreateFields(
                country_id="us", simulation_id=missing_simulation_id
            ),
        )


def test_a_simulation_gone_before_a_repoint_is_refused_by_its_foreign_key(
    monkeypatch: pytest.MonkeyPatch,
    owner_engine: Engine,
    catalogs: dict[str, CatalogRows],
    browsers: list[UUID],
    runtime_sessions: sessionmaker,
) -> None:
    with owner_engine.begin() as connection:
        simulation_id = store_simulation(connection, catalogs["uk"], policy_id=None)
    service = simulation_service(runtime_sessions)
    principal = browser(browsers)
    saved = service.create_user_simulation(
        principal=principal,
        association_input=UserSimulationCreateFields(
            country_id="uk", simulation_id=simulation_id
        ),
    )
    # As if the new simulation were deleted between the check and the update.
    monkeypatch.setattr(
        simulation_services,
        "read_simulation_exists",
        lambda *_args, **_kwargs: True,
    )
    missing_simulation_id = uuid4()

    with pytest.raises(
        AssociationSimulationNotFoundError,
        match=f"Simulation {missing_simulation_id} was not found in country 'uk'",
    ):
        service.patch_user_simulation(
            principal=principal,
            country_id="uk",
            association_id=saved.id,
            association_input=UserSimulationUpdateInput(
                simulation_id=missing_simulation_id
            ),
        )
