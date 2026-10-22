"""Publication refuses regions the certified data cannot select."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from policyengine_api.data.v2.catalog.region_data_verification import (
    WEIGHT_MATRIX_ROW_LOOKUPS,
    RegionDataVerificationError,
    load_weight_matrix_row_codes,
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
}
CONSTITUENCY_ROW_CODES = ("E14001063", "E14001064")


class FakeInspector:
    """Answers from fixed columns and matrix sizes, and records each artifact read."""

    def __init__(
        self,
        *,
        columns: dict[str, frozenset[str]] | None = None,
        matrix_rows: dict[str, int] | None = None,
        failure: Exception | None = None,
    ) -> None:
        self.columns = ALL_COLUMNS if columns is None else columns
        self.matrix_rows = (
            {"parliamentary_constituency_weights": len(CONSTITUENCY_ROW_CODES)}
            if matrix_rows is None
            else matrix_rows
        )
        self.failure = failure
        self.reads: list[tuple[str, str]] = []

    def household_columns(self, artifact: CertifiedArtifact) -> frozenset[str]:
        self.reads.append(("columns", artifact.name))
        if self.failure is not None:
            raise self.failure
        return self.columns[artifact.name]

    def weight_matrix_row_count(self, artifact: CertifiedArtifact) -> int:
        self.reads.append(("rows", artifact.name))
        if self.failure is not None:
            raise self.failure
        return self.matrix_rows[artifact.name]


def _verify(
    inspector: FakeInspector,
    *,
    countries: tuple[str, ...] = ("us", "uk"),
    row_codes: tuple[str, ...] = CONSTITUENCY_ROW_CODES,
) -> None:
    verify_region_data(
        normalized_catalog(),
        inspector,
        countries=countries,
        weight_matrix_row_codes={"parliamentary_constituency_weights": row_codes},
    )


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
            "parliamentary_constituency_weights",
            "example-org/example-uk-data",
            "parliamentary_constituency_weights.h5",
            "model",
        ),
    ]


def test_accepts_regions_whose_columns_and_matrix_rows_exist() -> None:
    inspector = FakeInspector()

    _verify(inspector)

    assert sorted(inspector.reads) == [
        ("columns", "microcosm_uk_2024_25"),
        ("columns", "populace_us_2024_acs_local"),
        ("rows", "parliamentary_constituency_weights"),
    ]


def test_reads_only_the_artifacts_of_the_countries_it_verifies() -> None:
    inspector = FakeInspector()

    _verify(inspector, countries=("us",))

    assert inspector.reads == [("columns", "populace_us_2024_acs_local")]


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


def test_rejects_a_region_code_missing_from_the_weight_matrix() -> None:
    with pytest.raises(
        RegionDataVerificationError,
        match=r"^the weight matrix parliamentary_constituency_weights has no row for "
        r"1 uk region \(constituency/E14001063\)$",
    ):
        _verify(FakeInspector(), row_codes=("E14001064", "E14001065"))


def test_rejects_a_weight_matrix_whose_rows_differ_from_its_lookup() -> None:
    inspector = FakeInspector(matrix_rows={"parliamentary_constituency_weights": 3})

    with pytest.raises(
        RegionDataVerificationError,
        match=r"^the weight matrix parliamentary_constituency_weights has 3 region "
        r"rows, but its row lookup lists 2 codes$",
    ):
        _verify(inspector)


def test_rejects_a_weight_matrix_without_a_row_lookup() -> None:
    with pytest.raises(
        RegionDataVerificationError,
        match=r"^no row lookup names the regions of the weight matrix "
        r"parliamentary_constituency_weights$",
    ):
        verify_region_data(
            normalized_catalog(),
            FakeInspector(),
            countries=("uk",),
            weight_matrix_row_codes={},
        )


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


def test_row_lookups_list_every_reference_code_in_matrix_order() -> None:
    constituencies = load_weight_matrix_row_codes(
        WEIGHT_MATRIX_ROW_LOOKUPS["parliamentary_constituency_weights"]
    )
    local_authorities = load_weight_matrix_row_codes(
        WEIGHT_MATRIX_ROW_LOOKUPS["local_authority_weights"]
    )

    assert len(constituencies) == len(set(constituencies)) == 650
    assert len(local_authorities) == len(set(local_authorities)) == 361
    assert constituencies[0] == "E14001063"
    assert local_authorities[0] == "E06000001"
