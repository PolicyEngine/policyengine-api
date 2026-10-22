"""Reading column names and weight-matrix sizes from certified HDF5 artifacts."""

from __future__ import annotations

from typing import TYPE_CHECKING

import h5py
import numpy as np
import pandas as pd
import pytest

from policyengine_api.data.v2.catalog.certified_data_inspection import (
    CertifiedDataReadError,
    HuggingFaceDataInspector,
    household_columns_in_hdf5,
    huggingface_path,
    weight_matrix_rows_in_hdf5,
)
from policyengine_api.data.v2.catalog.records import CertifiedArtifact

if TYPE_CHECKING:
    from pathlib import Path

HOUSEHOLDS = pd.DataFrame(
    {
        "household_id": [1, 2],
        "household_weight": [1.5, 2.5],
        "state_fips": [6, 36],
    }
)


def _artifact(
    *,
    name: str = "populace_us_2024_acs_local",
    repo_type: str = "dataset",
    revision: str = "populace-us-2024-buildo-acs-local-766b7c7-20261017T030317Z",
) -> CertifiedArtifact:
    return CertifiedArtifact(
        name=name,
        repo_id="policyengine/populace-us",
        repo_type=repo_type,
        path=f"{name}.h5",
        revision=revision,
        sha256=None,
    )


def _columns(path: Path) -> frozenset[str]:
    with h5py.File(path, "r") as h5:
        return household_columns_in_hdf5(h5)


def _rows(path: Path) -> int:
    with h5py.File(path, "r") as h5:
        return weight_matrix_rows_in_hdf5(h5)


def test_reads_columns_of_a_fixed_format_household_frame(tmp_path: Path) -> None:
    path = tmp_path / "fixed.h5"
    HOUSEHOLDS.to_hdf(path, key="household", format="fixed")

    assert _columns(path) == {"household_id", "household_weight", "state_fips"}


def test_reads_data_columns_of_a_table_format_household_frame(tmp_path: Path) -> None:
    path = tmp_path / "table.h5"
    frame = HOUSEHOLDS.assign(region=pd.Categorical(["LONDON", "WALES"]))
    frame.to_hdf(path, key="household", format="table", data_columns=True)

    assert _columns(path) == {
        "household_id",
        "household_weight",
        "state_fips",
        "region",
    }


# PyTables warns that year keys are not Python identifiers; policyengine-uk's
# multi-year files use the same keys.
@pytest.mark.filterwarnings("ignore:object name is not a valid Python identifier")
def test_keeps_only_columns_every_year_of_a_multi_year_file_has(
    tmp_path: Path,
) -> None:
    path = tmp_path / "years.h5"
    HOUSEHOLDS.to_hdf(path, key="household/2024", format="table", data_columns=True)
    HOUSEHOLDS.drop(columns="state_fips").to_hdf(
        path, key="household/2025", format="table", data_columns=True
    )

    assert _columns(path) == {"household_id", "household_weight"}


def test_reads_variable_names_of_a_core_format_file(tmp_path: Path) -> None:
    path = tmp_path / "core.h5"
    with h5py.File(path, "w") as h5:
        h5.create_dataset("state_fips/2024", data=np.array([6, 36]))
        h5.create_dataset("household_weight/2024", data=np.array([1.5, 2.5]))

    assert _columns(path) == {"state_fips", "household_weight"}


def test_refuses_a_table_whose_columns_are_stored_in_value_blocks(
    tmp_path: Path,
) -> None:
    path = tmp_path / "blocks.h5"
    HOUSEHOLDS.to_hdf(path, key="household", format="table")

    with pytest.raises(
        CertifiedDataReadError,
        match=r"^household table household stores columns in value blocks, whose "
        r"names cannot be read without unpickling$",
    ):
        _columns(path)


def test_refuses_a_household_group_that_holds_no_frame(tmp_path: Path) -> None:
    path = tmp_path / "empty.h5"
    with h5py.File(path, "w") as h5:
        h5.create_group("household")

    with pytest.raises(
        CertifiedDataReadError, match=r"^household group holds no data frame$"
    ):
        _columns(path)


def test_counts_the_region_rows_of_a_weight_matrix(tmp_path: Path) -> None:
    path = tmp_path / "matrix.h5"
    with h5py.File(path, "w") as h5:
        h5.create_dataset("2024", data=np.ones((3, 5)))
        h5.create_dataset("2025", data=np.ones((3, 5)))

    assert _rows(path) == 3


@pytest.mark.parametrize(
    ("shapes", "message"),
    [
        ({}, r"^the weight matrix has no year datasets$"),
        ({"2024": (3,)}, r"^the weight matrix entry 2024 is not two-dimensional$"),
        (
            {"2024": (3, 5), "2025": (4, 5)},
            r"^the weight matrix years disagree on the number of regions: \[3, 4\]$",
        ),
    ],
)
def test_refuses_an_inconsistent_weight_matrix(
    tmp_path: Path,
    shapes: dict[str, tuple[int, ...]],
    message: str,
) -> None:
    path = tmp_path / "matrix.h5"
    with h5py.File(path, "w") as h5:
        for year, shape in shapes.items():
            h5.create_dataset(year, data=np.ones(shape))

    with pytest.raises(CertifiedDataReadError, match=message):
        _rows(path)


def test_names_dataset_and_model_repository_files_at_their_revision() -> None:
    assert huggingface_path(_artifact()) == (
        "datasets/policyengine/populace-us@"
        "populace-us-2024-buildo-acs-local-766b7c7-20261017T030317Z/"
        "populace_us_2024_acs_local.h5"
    )
    assert huggingface_path(
        _artifact(name="enhanced_frs_2024_25", repo_type="model", revision="1.58.1")
    ) == ("policyengine/populace-us@1.58.1/enhanced_frs_2024_25.h5")
    assert huggingface_path(_artifact(revision="refs/pr/1")).startswith(
        "datasets/policyengine/populace-us@refs%2Fpr%2F1/"
    )


class FakeFileSystem:
    """Serves local files for Hugging Face paths and records how it was built."""

    def __init__(self, files: dict[str, Path]) -> None:
        self.files = files
        self.opened: list[str] = []

    def open(self, path: str, mode: str, *, block_size: int, cache_type: str):
        assert (mode, block_size, cache_type) == ("rb", 1 << 20, "blockcache")
        self.opened.append(path)
        return self.files[path].open("rb")


def test_inspector_reads_artifacts_through_an_authenticated_file_system(
    tmp_path: Path,
) -> None:
    dataset_path = tmp_path / "dataset.h5"
    HOUSEHOLDS.to_hdf(dataset_path, key="household", format="fixed")
    matrix_path = tmp_path / "matrix.h5"
    with h5py.File(matrix_path, "w") as h5:
        h5.create_dataset("2025", data=np.ones((2, 2)))
    dataset = _artifact()
    matrix = _artifact(name="parliamentary_constituency_weights", repo_type="model")
    file_system = FakeFileSystem(
        {
            huggingface_path(dataset): dataset_path,
            huggingface_path(matrix): matrix_path,
        }
    )
    tokens: list[str | None] = []

    def build_file_system(token: str | None) -> FakeFileSystem:
        tokens.append(token)
        return file_system

    inspector = HuggingFaceDataInspector(
        token="read-token", file_system_factory=build_file_system
    )

    assert "state_fips" in inspector.household_columns(dataset)
    assert inspector.weight_matrix_row_count(matrix) == 2
    assert tokens == ["read-token"]
    assert file_system.opened == [huggingface_path(dataset), huggingface_path(matrix)]
