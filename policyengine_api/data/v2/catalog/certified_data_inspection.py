"""Read household column names from certified HDF5 dataset files.

The artifacts are read from Hugging Face at their pinned revisions through
ranged requests. Only the 1 MB blocks holding the HDF5 metadata and the
column-name arrays are downloaded, a small part of each file; the household
arrays themselves are never read.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, BinaryIO, Protocol, TypeVar
from urllib.parse import quote

import h5py
from huggingface_hub import HfFileSystem

from policyengine_api.data.v2.catalog.errors import CertifiedDataReadError

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager

    from policyengine_api.data.v2.catalog.records import CertifiedArtifact

HOUSEHOLD_TABLE = "household"
# PyTables names the columns a table stores together "values_block_<n>"; their
# real names live only in pickled attributes.
VALUE_BLOCK_PREFIX = "values_block_"
TABLE_INDEX_COLUMN = "index"

_Result = TypeVar("_Result")


# HDF5 metadata is read in many small, scattered pieces; caching whole blocks of
# this size keeps the number of ranged requests low.
READ_BLOCK_BYTES = 1 << 20


class ArtifactFileSystem(Protocol):
    """Opens a file in a Hugging Face repository at a revision for reading."""

    def open(
        self, path: str, mode: str, *, block_size: int, cache_type: str
    ) -> AbstractContextManager[BinaryIO]:
        """Return a readable, seekable binary file that caches blocks it reads."""
        ...


def huggingface_path(artifact: CertifiedArtifact) -> str:
    """Return the Hugging Face file system path of an artifact at its revision."""
    prefix = "datasets/" if artifact.repo_type == "dataset" else ""
    revision = quote(artifact.revision, safe="")
    return f"{prefix}{artifact.repo_id}@{revision}/{artifact.path}"


def _text(value: object) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def _is_frame(group: h5py.Group) -> bool:
    return "axis0" in group or "table" in group


def _frame_columns(group: h5py.Group) -> frozenset[str]:
    """Return the column names of one pandas data frame stored in HDF5."""
    if "axis0" in group:
        return frozenset(_text(value) for value in group["axis0"][()])
    names = group["table"].dtype.names or ()
    if any(name.startswith(VALUE_BLOCK_PREFIX) for name in names):
        msg = (
            f"household table {group.name.lstrip('/')} stores columns in value "
            "blocks, whose names cannot be read without unpickling"
        )
        raise CertifiedDataReadError(msg)
    return frozenset(name for name in names if name != TABLE_INDEX_COLUMN)


def household_columns_in_hdf5(h5: h5py.File) -> frozenset[str]:
    """Return the household column names of a dataset file.

    A pandas file stores the household frame directly, or one frame per year
    (then only columns every year has count). A policyengine-core file stores
    one top-level entry per variable.
    """
    if HOUSEHOLD_TABLE not in h5:
        return frozenset(h5.keys())
    household = h5[HOUSEHOLD_TABLE]
    if not isinstance(household, h5py.Group):
        msg = "household entry is not an HDF5 group"
        raise CertifiedDataReadError(msg)
    if _is_frame(household):
        return _frame_columns(household)
    frames = [
        entry
        for entry in household.values()
        if isinstance(entry, h5py.Group) and _is_frame(entry)
    ]
    if not frames:
        msg = "household group holds no data frame"
        raise CertifiedDataReadError(msg)
    return frozenset.intersection(*(_frame_columns(frame) for frame in frames))


def _hugging_face_file_system(token: str | None) -> ArtifactFileSystem:
    return HfFileSystem(token=token)


class HuggingFaceDataInspector:
    """Reads certified artifacts from Hugging Face with an optional read token."""

    def __init__(
        self,
        *,
        token: str | None,
        file_system_factory: Callable[[str | None], ArtifactFileSystem] = (
            _hugging_face_file_system
        ),
    ) -> None:
        """Build the file system once; a token of None reads public data only."""
        self._file_system = file_system_factory(token)

    def _read(
        self,
        artifact: CertifiedArtifact,
        read: Callable[[h5py.File], _Result],
    ) -> _Result:
        with (
            self._file_system.open(
                huggingface_path(artifact),
                "rb",
                block_size=READ_BLOCK_BYTES,
                cache_type="blockcache",
            ) as handle,
            h5py.File(handle, "r") as h5,
        ):
            return read(h5)

    def household_columns(self, artifact: CertifiedArtifact) -> frozenset[str]:
        """Return the household column names of a dataset artifact."""
        return self._read(artifact, household_columns_in_hdf5)
