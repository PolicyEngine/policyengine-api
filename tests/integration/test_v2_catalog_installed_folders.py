"""Publish a few parameter folders of the installed PolicyEngine.py models.

CI doesn't load the complete installed catalog (about 1.2 million parameter
values). This test runs the real US and UK models through extraction and
publication instead, each reduced to the parameters under the folders in
SELECTED_FOLDERS, and checks that every extracted value comes back from
PostgreSQL unchanged. Extraction gets only what it needs besides those
parameters: each model's identity, package and release manifest, its national
region, and no variables.

tests/fixtures/v2_catalog_value_shapes.py covers the value shapes extraction
accepts that the installed models don't hold, such as text and mappings.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from importlib import metadata as importlib_metadata
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from policyengine_api.data.v2.catalog.extraction import extract_catalog
from policyengine_api.data.v2.catalog.publication import publish_catalog
from tests.fixtures.v2_catalog import RegionRegistry
from tests.integration.catalog_rows import assert_catalog_stored_unchanged

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping

    from sqlalchemy.engine import Engine

    from policyengine_api.data.v2.catalog.records import (
        NormalizedCatalog,
        ParameterValueRecord,
    )

REPO = Path(__file__).parents[2]
# The parameter folders this test publishes, by country, with why each is
# here. Between them they hold every value shape the installed models hold.
SELECTED_FOLDERS = {
    "us": {
        "gov.irs.income.bracket": (
            "income tax rates and thresholds broken down by bracket number and "
            "by filing status (SINGLE, JOINT, SEPARATE, HEAD_OF_HOUSEHOLD, "
            "SURVIVING_SPOUSE); the top bracket's thresholds are infinite"
        ),
        "gov.irs.payroll.social_security": (
            "plain rates and a cap, with a long history of values"
        ),
        "gov.aca.family_tier_states": (
            "booleans broken down by state, some starting in year 1, which .py "
            "reads from Core's 0000-01-01"
        ),
        "gov.aca.ineligible_immigration_statuses": "a list of enum names",
        "gov.irs.credits.premium_tax_credit.phase_out": (
            "bracket scales (rate[0].amount, rate[1].threshold, ...) whose "
            "upper brackets hold null values"
        ),
        "gov.states.ne.dhhs.child_care_subsidy.fpg_fraction": (
            "values in force for a single day, the only ones in the installed models"
        ),
    },
    "uk": {
        "gov.hmrc.income_tax.rates.uk": (
            "the UK income tax bracket scale: a rate and a threshold per bracket"
        ),
        "gov.dwp.state_pension.triple_lock": "UK booleans and a null value",
    },
}
EARLIEST = datetime(1, 1, 1, tzinfo=UTC)


def _in_folders(name: str, folders: Iterable[str]) -> bool:
    """Whether ``name`` is one of ``folders`` or lies under one."""
    return any(
        name == folder or name.startswith((f"{folder}.", f"{folder}["))
        for folder in folders
    )


def selected_model(country_id: str, model: object, folders: Iterable[str]) -> object:
    """Return ``model`` reduced to what extraction needs and ``folders``' parameters.

    Raise LookupError naming every folder the model no longer has, so a renamed
    or removed folder fails the test instead of shrinking it.
    """
    folders = tuple(folders)
    parameter_names = tuple(model.parameters_by_name)
    missing = [
        folder
        for folder in folders
        if not any(_in_folders(name, (folder,)) for name in parameter_names)
    ]
    if missing:
        msg = (
            f"The installed {country_id} model has no parameters under "
            f"{', '.join(missing)}. A folder was renamed or removed: choose one "
            "that holds the same values and update SELECTED_FOLDERS in "
            "tests/integration/test_v2_catalog_installed_folders.py."
        )
        raise LookupError(msg)
    return SimpleNamespace(
        model=model.model,
        model_package=model.model_package,
        release_manifest=model.release_manifest,
        region_registry=RegionRegistry(
            country_id,
            [region for region in model.region_registry if region.code == country_id],
        ),
        variables_by_name={},
        parameter_nodes_by_name={
            name: node
            for name, node in model.parameter_nodes_by_name.items()
            if _in_folders(name, folders)
        },
        parameters_by_name={
            name: parameter
            for name, parameter in model.parameters_by_name.items()
            if _in_folders(name, folders)
        },
    )


@pytest.fixture(scope="module")
def installed_models() -> dict[str, object]:
    """Return the installed US and UK models; importing policyengine builds both."""
    import policyengine

    return {
        country_id: getattr(policyengine, country_id).model
        for country_id in SELECTED_FOLDERS
    }


@pytest.fixture(scope="module")
def selected_catalog(installed_models: Mapping[str, object]) -> NormalizedCatalog:
    """Return the catalog extracted from the installed models' selected folders."""
    from policyengine.bundle import get_current_bundle

    return extract_catalog(
        bundle=get_current_bundle(),
        policyengine_version=importlib_metadata.version("policyengine"),
        models={
            country_id: selected_model(country_id, model, SELECTED_FOLDERS[country_id])
            for country_id, model in installed_models.items()
        },
    )


@pytest.fixture
def publication_engine(disposable_v2_database_url: str) -> Iterator[Engine]:
    """Return an engine for the disposable v2 database, with no catalog in it."""
    command.upgrade(Config(str(REPO / "alembic-v2.ini")), "head")
    engine = create_engine(disposable_v2_database_url, poolclass=NullPool)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE tax_benefit_models CASCADE"))
    yield engine
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE tax_benefit_models CASCADE"))
    engine.dispose()


def _values(catalog: NormalizedCatalog) -> list[ParameterValueRecord]:
    return [
        value
        for country in catalog.countries
        for parameter in country.parameters
        for value in parameter.values
    ]


def test_a_folder_missing_from_the_installed_model_fails_by_name() -> None:
    model = SimpleNamespace(parameters_by_name={"gov.irs.payroll.rate": object()})

    with pytest.raises(
        LookupError, match=r"no parameters under gov\.renamed\. A folder"
    ):
        selected_model("us", model, ("gov.irs.payroll", "gov.renamed"))


def test_the_installed_models_are_the_us_and_uk_models(
    installed_models: Mapping[str, object],
) -> None:
    # The first test to use installed_models, so pytest --durations reports
    # its setup as the cost of importing .py and building both models, apart
    # from extraction, which is the next test's setup.
    assert {
        country_id: model.model.id for country_id, model in installed_models.items()
    } == {"us": "policyengine-us", "uk": "policyengine-uk"}


def test_selected_folders_hold_every_value_shape_the_installed_models_hold(
    selected_catalog: NormalizedCatalog,
) -> None:
    values = _values(selected_catalog)
    stored = [value.value_json for value in values]
    names = [
        parameter.name
        for country in selected_catalog.countries
        for parameter in country.parameters
    ]
    shapes = {
        "a boolean": any(isinstance(value, bool) for value in stored),
        "an integer": any(type(value) is int for value in stored),
        "a fraction": any(
            isinstance(value, float) and not value.is_integer() for value in stored
        ),
        "an infinity, stored as text": "Infinity" in stored,
        "a null": None in stored,
        "a list": any(isinstance(value, list) and value for value in stored),
        "a bracket scale": any("[" in name for name in names),
        "a breakdown by state": any(name.endswith(".CA") for name in names),
        "a breakdown by filing status": any(name.endswith(".JOINT") for name in names),
        "a value in force for one day": any(
            value.start_date == value.end_date for value in values
        ),
        "a start in year 1": any(value.start_date == EARLIEST for value in values),
        "an open-ended value": any(value.end_date is None for value in values),
    }

    assert [shape for shape, held in shapes.items() if not held] == [], (
        "The selected folders no longer hold these shapes; add a folder that "
        "does to SELECTED_FOLDERS."
    )
    assert all(not isinstance(value, float) or math.isfinite(value) for value in stored)


def test_selected_folders_publish_and_come_back_unchanged(
    selected_catalog: NormalizedCatalog,
    publication_engine: Engine,
) -> None:
    publish_catalog(publication_engine, selected_catalog)
    # Publishing the same version again compares every stored row with the
    # catalog in both directions and fails on any difference.
    publish_catalog(publication_engine, selected_catalog)

    assert_catalog_stored_unchanged(publication_engine, selected_catalog)
