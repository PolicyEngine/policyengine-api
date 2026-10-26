"""Publication refuses regions the certified data cannot select."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from policyengine_api.data.v2.catalog.errors import CertifiedDataReadError
from policyengine_api.data.v2.catalog.region_data_verification import (
    RegionDataVerificationError,
    verify_region_data,
)
from tests.fixtures.v2_catalog import normalized_catalog

if TYPE_CHECKING:
    from policyengine_api.data.v2.catalog.records import CertifiedArtifact

ALL_COLUMNS = {
    "populace_us_2024_acs_local": frozenset(
        {"state_fips", "congressional_district_geoid", "household_weight"}
    ),
    "microcosm_uk_2024_25": frozenset({"region", "household_weight"}),
    "microcosm_uk_2024_25_dense": frozenset(
        {"constituency_code_oa", "la_code_oa", "household_weight"}
    ),
}


class FakeInspector:
    """Answers from fixed columns, and records each artifact read."""

    def __init__(
        self,
        *,
        columns: dict[str, frozenset[str]] | None = None,
        failure: Exception | None = None,
    ) -> None:
        self.columns = ALL_COLUMNS if columns is None else columns
        self.failure = failure
        self.reads: list[str] = []

    def household_columns(self, artifact: CertifiedArtifact) -> frozenset[str]:
        self.reads.append(artifact.name)
        if self.failure is not None:
            raise self.failure
        return self.columns[artifact.name]


def _verify(
    inspector: FakeInspector,
    *,
    countries: tuple[str, ...] = ("us", "uk"),
) -> None:
    verify_region_data(normalized_catalog(), inspector, countries=countries)


def test_catalog_records_only_the_artifacts_its_filters_read() -> None:
    catalog = normalized_catalog()

    assert [
        (artifact.name, artifact.repo_id, artifact.repo_type, artifact.revision)
        for artifact in catalog.country("us").certified_artifacts
    ] == [
        (
            "populace_us_2024_acs_local",
            "policyengine/populace-us",
            "dataset",
            "fixture",
        )
    ]
    assert [
        (artifact.name, artifact.repo_id, artifact.path, artifact.repo_type)
        for artifact in catalog.country("uk").certified_artifacts
    ] == [
        (
            "microcosm_uk_2024_25",
            "example-org/example-uk-data",
            "microcosm_uk_2024_25.h5",
            "model",
        ),
        (
            "microcosm_uk_2024_25_dense",
            "example-org/example-uk-data",
            "microcosm_uk_2024_25_dense.h5",
            "model",
        ),
    ]


def test_accepts_regions_whose_filter_columns_exist() -> None:
    inspector = FakeInspector()

    _verify(inspector)

    assert sorted(inspector.reads) == [
        "microcosm_uk_2024_25",
        "microcosm_uk_2024_25_dense",
        "populace_us_2024_acs_local",
    ]


def test_reads_only_the_artifacts_of_the_countries_it_verifies() -> None:
    inspector = FakeInspector()

    _verify(inspector, countries=("us",))

    assert inspector.reads == ["populace_us_2024_acs_local"]


def test_verifies_nothing_when_every_version_is_already_published() -> None:
    inspector = FakeInspector(failure=AssertionError("must not read"))

    _verify(inspector, countries=())

    assert inspector.reads == []


def test_rejects_a_filter_column_missing_from_the_dataset() -> None:
    inspector = FakeInspector(
        columns={
            **ALL_COLUMNS,
            "populace_us_2024_acs_local": frozenset({"state_fips"}),
        }
    )

    with pytest.raises(
        RegionDataVerificationError,
        match=r"^the certified dataset populace_us_2024_acs_local has no household "
        r"column congressional_district_geoid, which 1 us region filters on "
        r"\(congressional_district/CA-01\)$",
    ):
        _verify(inspector)


def test_rejects_a_local_area_dataset_without_the_area_code_column() -> None:
    inspector = FakeInspector(
        columns={
            **ALL_COLUMNS,
            "microcosm_uk_2024_25_dense": frozenset({"la_code_oa"}),
        }
    )

    with pytest.raises(
        RegionDataVerificationError,
        match=r"^the certified dataset microcosm_uk_2024_25_dense has no household "
        r"column constituency_code_oa, which 1 uk region filters on "
        r"\(constituency/E14001063\)$",
    ):
        _verify(inspector, countries=("uk",))


def test_reports_an_unreadable_artifact_without_its_error_text() -> None:
    inspector = FakeInspector(
        failure=PermissionError("403 for https://example.test/?token=do-not-print")
    )

    with pytest.raises(RegionDataVerificationError) as raised:
        _verify(inspector, countries=("us",))

    assert str(raised.value) == (
        "could not read the certified artifact populace_us_2024_acs_local: "
        "PermissionError"
    )
    assert "do-not-print" not in str(raised.value)
    assert "fixture" not in str(raised.value)


def test_reports_an_artifact_structure_error_with_its_own_message() -> None:
    inspector = FakeInspector(
        failure=CertifiedDataReadError("household group holds no data frame")
    )

    with pytest.raises(
        RegionDataVerificationError,
        match=r"^the certified artifact populace_us_2024_acs_local cannot be "
        r"checked: household group holds no data frame$",
    ):
        _verify(inspector, countries=("us",))


def test_passes_on_a_verification_error_the_inspector_raises() -> None:
    inspector = FakeInspector(failure=RegionDataVerificationError("already explained"))

    with pytest.raises(RegionDataVerificationError, match=r"^already explained$"):
        _verify(inspector, countries=("us",))
