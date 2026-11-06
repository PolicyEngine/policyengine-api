"""Choosing the stored catalog versions that pruning removes current-law values from.

Catalog publication keeps, for each model of the catalog it publishes, the
version it published (the installed one) and the most recently created other
version (the previous release's), and prunes every other stored version of that
model that is not pruned already.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import sqlalchemy as sa

from policyengine_api.data.v2.catalog import publication_pruning
from policyengine_api.data.v2.catalog.publication_pruning import (
    StoredCatalogVersion,
    catalog_versions_to_prune,
    pruning_failure,
)

FIRST_PUBLICATION = datetime(2026, 1, 5, 9, 30, tzinfo=UTC)
US_MODEL = "policyengine-us"
UK_MODEL = "policyengine-uk"


def _stored(
    model_name: str,
    version: str,
    *,
    days_after_first: int,
    values_pruned: bool = False,
) -> StoredCatalogVersion:
    return StoredCatalogVersion(
        id=uuid4(),
        model_name=model_name,
        version=version,
        created_at=FIRST_PUBLICATION + timedelta(days=days_after_first),
        values_pruned=values_pruned,
    )


def _versions(chosen: tuple[StoredCatalogVersion, ...]) -> list[tuple[str, str]]:
    return [(stored.model_name, stored.version) for stored in chosen]


def test_keeps_the_installed_and_the_most_recently_created_other_version() -> None:
    stored_versions = [
        _stored(US_MODEL, "5.0.3", days_after_first=30),
        _stored(US_MODEL, "5.0.1", days_after_first=0),
        _stored(US_MODEL, "5.0.4", days_after_first=45),
        _stored(US_MODEL, "5.0.2", days_after_first=10),
    ]

    chosen = catalog_versions_to_prune(stored_versions, {US_MODEL: "5.0.4"})

    # Oldest first; 5.0.3 is the previous release's version.
    assert _versions(chosen) == [(US_MODEL, "5.0.1"), (US_MODEL, "5.0.2")]


def test_an_installed_version_older_than_the_others_is_kept_after_a_rollback() -> None:
    stored_versions = [
        _stored(US_MODEL, "5.0.1", days_after_first=0),
        _stored(US_MODEL, "5.0.2", days_after_first=10),
        _stored(US_MODEL, "5.0.3", days_after_first=30),
        _stored(US_MODEL, "5.0.4", days_after_first=45),
    ]

    chosen = catalog_versions_to_prune(stored_versions, {US_MODEL: "5.0.1"})

    # The installed 5.0.1 and the most recently created other version, 5.0.4,
    # are kept.
    assert _versions(chosen) == [(US_MODEL, "5.0.2"), (US_MODEL, "5.0.3")]


def test_versions_already_pruned_are_not_pruned_again() -> None:
    stored_versions = [
        _stored(US_MODEL, "5.0.1", days_after_first=0, values_pruned=True),
        _stored(US_MODEL, "5.0.2", days_after_first=10),
        # The most recently created other version stays kept although an
        # earlier run pruned it; no older version is kept in its place.
        _stored(US_MODEL, "5.0.3", days_after_first=30, values_pruned=True),
        _stored(US_MODEL, "5.0.4", days_after_first=45),
    ]

    chosen = catalog_versions_to_prune(stored_versions, {US_MODEL: "5.0.4"})

    assert _versions(chosen) == [(US_MODEL, "5.0.2")]


def test_each_country_model_is_chosen_from_separately() -> None:
    stored_versions = [
        _stored(US_MODEL, "5.0.1", days_after_first=0),
        _stored(UK_MODEL, "5.0.1", days_after_first=0),
        _stored(US_MODEL, "5.0.2", days_after_first=10),
        _stored(UK_MODEL, "5.0.3", days_after_first=30),
        _stored(US_MODEL, "5.0.3", days_after_first=30),
        _stored(UK_MODEL, "5.0.4", days_after_first=45),
        # A model the published catalog doesn't name keeps every version.
        _stored("policyengine-retired", "1.0.0", days_after_first=0),
        _stored("policyengine-retired", "1.0.1", days_after_first=1),
        _stored("policyengine-retired", "1.0.2", days_after_first=2),
    ]

    chosen = catalog_versions_to_prune(
        stored_versions, {US_MODEL: "5.0.3", UK_MODEL: "5.0.4"}
    )

    # The US keeps 5.0.3 and 5.0.2; the UK keeps 5.0.4 and 5.0.3. Models are
    # listed in name order.
    assert _versions(chosen) == [(UK_MODEL, "5.0.1"), (US_MODEL, "5.0.1")]


def test_two_stored_versions_of_a_model_leave_nothing_to_prune() -> None:
    stored_versions = [
        _stored(US_MODEL, "5.0.1", days_after_first=0),
        _stored(US_MODEL, "5.0.2", days_after_first=10),
        _stored(UK_MODEL, "5.0.2", days_after_first=10),
    ]

    assert (
        catalog_versions_to_prune(
            stored_versions, {US_MODEL: "5.0.2", UK_MODEL: "5.0.2"}
        )
        == ()
    )


def test_a_pruning_failure_names_the_database_error_but_no_statement_or_row() -> None:
    # Named and coded as psycopg names and codes the error.
    division_by_zero = type("DivisionByZero", (Exception,), {"sqlstate": "22012"})
    version_id = uuid4()
    error = sa.exc.DataError(
        "DELETE FROM parameter_values WHERE parameter_values.parameter_id IN "
        "(SELECT parameters.id FROM parameters WHERE "
        "parameters.tax_benefit_model_version_id = %(version_id)s)",
        {"version_id": version_id},
        division_by_zero("division by zero near 'gov.example.rate' = 0.25"),
    )

    failure = pruning_failure("us", "5.0.1", error)

    assert failure.country_id == "us"
    assert failure.policyengine_version == "5.0.1"
    assert failure.error_type == "DataError"
    assert failure.message == (
        "pruning the us catalog version 5.0.1 failed and was rolled back: the "
        "database reported DivisionByZero (SQLSTATE 22012)"
    )
    for row_data in (str(version_id), "gov.example.rate", "0.25", "DELETE"):
        assert row_data not in failure.message


def test_a_failure_before_any_version_is_chosen_names_no_version() -> None:
    # Named and coded as psycopg names and codes the error.
    query_canceled = type("QueryCanceled", (Exception,), {"sqlstate": "57014"})
    error = sa.exc.OperationalError(
        "SELECT tax_benefit_model_versions.id FROM tax_benefit_model_versions",
        {},
        query_canceled("canceling statement due to statement timeout"),
    )

    failure = pruning_failure("uk", None, error)

    assert failure.country_id == "uk"
    assert failure.policyengine_version is None
    assert failure.error_type == "OperationalError"
    assert failure.message == (
        "reading the stored uk catalog versions to choose which to prune "
        "failed: the database reported QueryCanceled (SQLSTATE 57014)"
    )


def test_a_failure_that_is_not_a_database_error_names_only_its_class() -> None:
    error = KeyError("gov.example.rate = 0.25")

    failure = pruning_failure("us", "5.0.1", error)

    assert failure.error_type == "KeyError"
    assert failure.message == (
        "pruning the us catalog version 5.0.1 failed and was rolled back: it "
        "raised KeyError"
    )
    for row_data in ("gov.example.rate", "0.25"):
        assert row_data not in failure.message


def test_a_run_prunes_at_most_two_versions_oldest_first() -> None:
    chosen = (
        _stored(UK_MODEL, "5.0.2", days_after_first=10),
        _stored(UK_MODEL, "5.0.1", days_after_first=0),
        _stored(US_MODEL, "5.0.1", days_after_first=0),
        _stored(US_MODEL, "5.0.2", days_after_first=10),
        _stored(US_MODEL, "5.0.3", days_after_first=30),
    )

    this_run, left_to_prune = publication_pruning.catalog_versions_to_prune_now(chosen)

    assert publication_pruning.MAX_CATALOG_VERSIONS_PRUNED_PER_RUN == 2
    # Versions created at the same instant, as one publication creates both
    # countries' versions, are ordered by model name.
    assert _versions(this_run) == [(UK_MODEL, "5.0.1"), (US_MODEL, "5.0.1")]
    assert left_to_prune == 3


def test_a_run_with_no_more_than_the_limit_prunes_them_all() -> None:
    chosen = (_stored(US_MODEL, "5.0.1", days_after_first=0),)

    this_run, left_to_prune = publication_pruning.catalog_versions_to_prune_now(chosen)

    assert _versions(this_run) == [(US_MODEL, "5.0.1")]
    assert left_to_prune == 0
