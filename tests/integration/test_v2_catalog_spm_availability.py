"""Record SPM availability on published catalog versions in disposable Postgres.

Catalog publication records it as ``policyengine_v2_catalog_writer``, whose
declared privileges must cover the update (rule
``api.v2.runtime-privileges-tested-as-runtime-role``).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from uuid import uuid4

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlmodel import col

from policyengine_api.constants import REPO
from policyengine_api.data.v2.catalog.publication_types import (
    CatalogPublicationError,
    SPMAvailabilityRecording,
)
from policyengine_api.data.v2.catalog.spm_availability import (
    record_published_spm_availability,
    record_spm_availability,
)
from policyengine_api.data.v2.models import TaxBenefitModel, TaxBenefitModelVersion
from policyengine_api.data.v2.privileges import CATALOG_WRITER_ROLE
from tests.integration.simulation_rows import add_row

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from uuid import UUID

    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

AVAILABLE = {"available": True, "settings_schema": {}, "defaults": {"scenario": "x"}}
UNAVAILABLE = {"available": False}


def _delete_models(sessions: sessionmaker[Session], model_ids: Iterable[UUID]) -> None:
    """Delete the test's models and their versions."""
    with sessions.begin() as session:
        for model_id in model_ids:
            session.execute(
                sa.delete(TaxBenefitModelVersion).where(
                    col(TaxBenefitModelVersion.model_id) == model_id
                )
            )
            session.execute(
                sa.delete(TaxBenefitModel).where(col(TaxBenefitModel.id) == model_id)
            )


def test_availability_fills_only_the_named_version_and_only_once(
    v2_owner_sessions: sessionmaker[Session],
    v2_sessions_as_role: Callable[[str], sessionmaker[Session]],
) -> None:
    command.upgrade(Config(str(REPO / "alembic-v2.ini")), "head")
    writer_sessions = v2_sessions_as_role(CATALOG_WRITER_ROLE)
    model_id, version_id, other_version_id = uuid4(), uuid4(), uuid4()
    model_name = f"policyengine-us-{model_id.hex[:8]}"
    try:
        with v2_owner_sessions.begin() as session:
            add_row(session, TaxBenefitModel, id=model_id, name=model_name)
            for identifier, version in (
                (version_id, "1.450.0"),
                (other_version_id, "1.449.0"),
            ):
                add_row(
                    session,
                    TaxBenefitModelVersion,
                    id=identifier,
                    model_id=model_id,
                    version=version,
                    current_law_id=2,
                    metadata_time_periods=[2026],
                )
        with writer_sessions.begin() as session:
            first = record_spm_availability(
                session,
                model_name=model_name,
                version="1.450.0",
                availability=AVAILABLE,
            )
            again = record_spm_availability(
                session,
                model_name=model_name,
                version="1.450.0",
                availability=UNAVAILABLE,
            )
        with v2_owner_sessions() as session:
            stored = dict(
                session.execute(
                    sa.select(
                        col(TaxBenefitModelVersion.id),
                        col(TaxBenefitModelVersion.spm_availability),
                    ).where(col(TaxBenefitModelVersion.model_id) == model_id)
                ).all()
            )
    finally:
        _delete_models(v2_owner_sessions, [model_id])

    assert first
    assert not again
    assert stored == {version_id: AVAILABLE, other_version_id: None}


def _unreadable_versions(_url: str) -> object:
    msg = "the simulation service's versions could not be read"
    raise CatalogPublicationError(msg)


def test_publication_lists_only_versions_still_unrecorded(
    v2_owner_sessions: sessionmaker[Session],
    v2_sessions_as_role: Callable[[str], sessionmaker[Session]],
) -> None:
    command.upgrade(Config(str(REPO / "alembic-v2.ini")), "head")
    writer_sessions = v2_sessions_as_role(CATALOG_WRITER_ROLE)
    model_ids = {"us": uuid4(), "uk": uuid4()}
    model_names = {
        country_id: f"policyengine-{country_id}-{model_id.hex[:8]}"
        for country_id, model_id in model_ids.items()
    }
    catalog = SimpleNamespace(
        policyengine_version="6.10.0",
        countries=[
            SimpleNamespace(
                country_id=country_id,
                model=SimpleNamespace(name=model_names[country_id]),
                model_version=SimpleNamespace(version="1.450.0"),
            )
            for country_id in ("uk", "us")
        ],
    )
    try:
        with v2_owner_sessions.begin() as session:
            for country_id, model_id in model_ids.items():
                add_row(
                    session, TaxBenefitModel, id=model_id, name=model_names[country_id]
                )
                # An earlier publication recorded the US version. The UK one
                # leaves the column out, as publication's insert does, so it
                # holds SQL NULL rather than JSON null.
                recorded_earlier = (
                    {"spm_availability": AVAILABLE} if country_id == "us" else {}
                )
                add_row(
                    session,
                    TaxBenefitModelVersion,
                    id=uuid4(),
                    model_id=model_id,
                    version="1.450.0",
                    current_law_id=2,
                    metadata_time_periods=[2026],
                    **recorded_earlier,
                )
        unreadable = record_published_spm_availability(
            writer_sessions,
            catalog,
            {"SIMULATION_ENTRYPOINT_URL": "https://simulation.example"},
            fetch_versions=_unreadable_versions,
        )
        # The simulation service serves no PolicyEngine.py version yet.
        not_served = record_published_spm_availability(
            writer_sessions,
            catalog,
            {"SIMULATION_ENTRYPOINT_URL": "https://simulation.example"},
            fetch_versions=lambda _url: {"policyengine": {}},
        )
    finally:
        _delete_models(v2_owner_sessions, model_ids.values())

    assert unreadable == SPMAvailabilityRecording(
        not_recorded=(("uk", "1.450.0"),),
        versions_unreadable="the simulation service's versions could not be read",
    )
    # The UK version is recorded unavailable; the US one keeps its value.
    assert not_served == SPMAvailabilityRecording(recorded=(("uk", "1.450.0", False),))
