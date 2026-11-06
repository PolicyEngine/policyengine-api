"""Disposable-Postgres coverage: republication and a stored version's time periods.

A stored catalog version takes the staged time periods (metadata_time_periods),
the years the Public API offers for it, which come from
policyengine_api.economy_years. Every other column and table must still match.
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.pool import NullPool

from policyengine_api.data.v2.catalog import publication as publication_module
from policyengine_api.data.v2.catalog.publication import (
    CatalogPublicationError,
    publish_catalog,
)
from policyengine_api.data.v2.settings import V2_MIGRATION_DATABASE_URL
from policyengine_api.economy_years import UK_ECONOMY_YEARS, US_ECONOMY_YEARS
from tests.fixtures.v2_catalog import normalized_catalog

REPO = Path(__file__).parents[2]
DISPOSABLE_DATABASE = "policyengine_v2_alembic_test"
# The US years catalog versions were stored with before 2022 and 2023 were
# dropped: 2035 to 2022, newest first.
PREVIOUS_US_YEARS = tuple(range(2035, 2021, -1))
CATALOG_TABLES = (
    "tax_benefit_models",
    "tax_benefit_model_versions",
    "variables",
    "parameter_nodes",
    "parameters",
    "parameter_values",
    "datasets",
    "regions",
)


def _disposable_url() -> str:
    database_url = os.environ.get(V2_MIGRATION_DATABASE_URL, "")
    if not database_url:
        pytest.skip(f"{V2_MIGRATION_DATABASE_URL} is not set")
    url = make_url(database_url)
    if url.database != DISPOSABLE_DATABASE or url.host not in {
        "localhost",
        "127.0.0.1",
        "::1",
        "postgres",
    }:
        pytest.fail("catalog publication tests require disposable local Postgres")
    return database_url


@pytest.fixture
def publication_engine() -> Engine:
    database_url = _disposable_url()
    command.upgrade(Config(str(REPO / "alembic-v2.ini")), "head")
    engine = create_engine(database_url, poolclass=NullPool)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE tax_benefit_models CASCADE"))
    yield engine
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE tax_benefit_models CASCADE"))
    engine.dispose()


def _with_us_years(catalog, years: tuple[int, ...]):
    us = catalog.country("us")
    model_version = replace(us.model_version, metadata_time_periods=years)
    return replace(
        catalog,
        countries=(replace(us, model_version=model_version), catalog.country("uk")),
    )


def _stored_years(engine: Engine) -> dict[str, list[int]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT model.name, version.metadata_time_periods "
                "FROM tax_benefit_model_versions AS version "
                "JOIN tax_benefit_models AS model ON model.id = version.model_id"
            )
        ).all()
    return {model_name: list(years) for model_name, years in rows}


def _identifiers(engine: Engine) -> dict[str, tuple[str, ...]]:
    with engine.connect() as connection:
        return {
            table_name: tuple(
                str(value)
                for value in connection.execute(
                    text(f"SELECT id FROM {table_name} ORDER BY id")
                ).scalars()
            )
            for table_name in CATALOG_TABLES
        }


def test_stored_version_takes_the_staged_time_periods_and_logs_them(
    publication_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = normalized_catalog()
    publish_catalog(publication_engine, _with_us_years(catalog, PREVIOUS_US_YEARS))
    assert _stored_years(publication_engine) == {
        "policyengine-us": list(PREVIOUS_US_YEARS),
        "policyengine-uk": list(UK_ECONOMY_YEARS),
    }
    before_ids = _identifiers(publication_engine)
    # Alembic's logging configuration disables existing loggers, so the
    # warnings are recorded where they are emitted.
    warnings: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        publication_module.LOGGER,
        "warning",
        lambda message, *args, **kwargs: warnings.append((message % args, kwargs)),
    )

    evidence = publish_catalog(publication_engine, catalog)

    assert _stored_years(publication_engine) == {
        "policyengine-us": list(US_ECONOMY_YEARS),
        "policyengine-uk": list(UK_ECONOMY_YEARS),
    }
    assert _identifiers(publication_engine) == before_ids
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
    again = publish_catalog(publication_engine, catalog)
    assert again.time_period_updates == ()
    assert again.as_dict()["updated_time_periods"] == []


def test_stored_version_with_changed_time_periods_still_fails_on_other_tables(
    publication_engine: Engine,
) -> None:
    catalog = normalized_catalog()
    publish_catalog(publication_engine, _with_us_years(catalog, PREVIOUS_US_YEARS))
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
        publish_catalog(publication_engine, changed)

    assert _stored_years(publication_engine)["policyengine-us"] == list(
        PREVIOUS_US_YEARS
    )
