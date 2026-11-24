"""Disposable-Postgres coverage: republication and a stored version's time periods.

A stored catalog version takes the staged time periods (metadata_time_periods),
the years API v1 offers for it, which come from
policyengine_api.economy_years. Every other column and table must still match.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select
from sqlmodel import col

from policyengine_api.data.v2.catalog import publication as publication_module
from policyengine_api.data.v2.catalog.publication import (
    CatalogPublicationError,
    publish_catalog,
)
from policyengine_api.data.v2.models import TaxBenefitModel, TaxBenefitModelVersion
from policyengine_api.economy_years import UK_ECONOMY_YEARS, US_ECONOMY_YEARS
from tests.fixtures.v2_catalog import normalized_catalog
from tests.integration.catalog_publication_support import (
    emptied_catalog,
    stored_identifiers,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

# The US years catalog versions were stored with before 2022 and 2023 were
# dropped: 2035 to 2022, newest first.
PREVIOUS_US_YEARS = tuple(range(2035, 2021, -1))


@pytest.fixture
def publication_sessions(
    v2_owner_sessions: sessionmaker[Session],
) -> Iterator[sessionmaker[Session]]:
    with emptied_catalog(v2_owner_sessions) as sessions:
        yield sessions


def _with_us_years(catalog, years: tuple[int, ...]):
    us = catalog.country("us")
    model_version = replace(us.model_version, metadata_time_periods=years)
    return replace(
        catalog,
        countries=(replace(us, model_version=model_version), catalog.country("uk")),
    )


def _stored_years(sessions: sessionmaker[Session]) -> dict[str, list[int]]:
    with sessions() as session:
        rows = session.execute(
            select(
                col(TaxBenefitModel.name),
                col(TaxBenefitModelVersion.metadata_time_periods),
            ).join(
                TaxBenefitModel,
                col(TaxBenefitModel.id) == col(TaxBenefitModelVersion.model_id),
            )
        ).all()
    return {model_name: list(years) for model_name, years in rows}


def test_stored_version_takes_the_staged_time_periods_and_logs_them(
    publication_sessions: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = normalized_catalog()
    publish_catalog(publication_sessions, _with_us_years(catalog, PREVIOUS_US_YEARS))
    assert _stored_years(publication_sessions) == {
        "policyengine-us": list(PREVIOUS_US_YEARS),
        "policyengine-uk": list(UK_ECONOMY_YEARS),
    }
    before_ids = stored_identifiers(publication_sessions)
    # Alembic's logging configuration disables existing loggers, so the
    # warnings are recorded where they are emitted.
    warnings: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        publication_module.LOGGER,
        "warning",
        lambda message, *args, **kwargs: warnings.append((message % args, kwargs)),
    )

    evidence = publish_catalog(publication_sessions, catalog)

    assert _stored_years(publication_sessions) == {
        "policyengine-us": list(US_ECONOMY_YEARS),
        "policyengine-uk": list(UK_ECONOMY_YEARS),
    }
    assert stored_identifiers(publication_sessions) == before_ids
    version = catalog.policyengine_version
    assert evidence.time_period_updates == (
        ("us", version, PREVIOUS_US_YEARS, US_ECONOMY_YEARS),
    )
    assert evidence.as_dict()["updated_time_periods"] == [
        {
            "country_id": "us",
            "policyengine_version": version,
            "previous_time_periods": list(PREVIOUS_US_YEARS),
            "time_periods": list(US_ECONOMY_YEARS),
        }
    ]
    notices = [
        (message, keywords["extra"]["policyengine_attributes"])
        for message, keywords in warnings
        if message.startswith("replaced the time periods")
    ]
    assert notices == [
        (
            f"replaced the time periods of the stored us catalog version {version}: "
            f"{list(PREVIOUS_US_YEARS)} became {list(US_ECONOMY_YEARS)}",
            {
                "country_id": "us",
                "policyengine_version": version,
                "stored_time_periods": list(PREVIOUS_US_YEARS),
                "staged_time_periods": list(US_ECONOMY_YEARS),
            },
        )
    ]

    # Publishing the same years again changes and reports nothing.
    again = publish_catalog(publication_sessions, catalog)
    assert again.time_period_updates == ()
    assert again.as_dict()["updated_time_periods"] == []


def test_stored_version_with_changed_time_periods_still_fails_on_other_tables(
    publication_sessions: sessionmaker[Session],
) -> None:
    catalog = normalized_catalog()
    publish_catalog(publication_sessions, _with_us_years(catalog, PREVIOUS_US_YEARS))
    us = catalog.country("us")
    changed = replace(
        catalog,
        countries=(
            replace(us, variables=(replace(us.variables[0], label="Changed"),)),
            catalog.country("uk"),
        ),
    )

    with pytest.raises(
        CatalogPublicationError,
        match=r"^the stored us catalog version 5\.0\.4 differs from the staged "
        r"catalog in its variables$",
    ):
        publish_catalog(publication_sessions, changed)

    assert _stored_years(publication_sessions)["policyengine-us"] == list(
        PREVIOUS_US_YEARS
    )
