"""Versioned declarative Stage 8 application data for Alembic autogeneration."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from policyengine_api.data.v2.table_inventory import EXPECTED_V2_TABLES


REFERENCE_DATA_FORMAT_VERSION = 1
VALIDATION_MODEL_ID = "80000000-0000-4000-8000-000000000001"
VALIDATION_MODEL_VERSION_ID = "80000000-0000-4000-8000-000000000002"
VALIDATION_TIMESTAMP = "2026-08-14T00:00:00+00:00"


class ReferenceDataDeclarationError(ValueError):
    """Raised when declarative data is not safe for deterministic generation."""


@dataclass(frozen=True)
class ReferenceRow:
    key: MappingProxyType
    values: MappingProxyType

    @classmethod
    def create(cls, *, key: dict[str, Any], values: dict[str, Any]) -> "ReferenceRow":
        if not key or any(value is None for value in key.values()):
            raise ReferenceDataDeclarationError(
                "reference rows require non-null stable key values"
            )
        overlap = set(key) & set(values)
        if overlap:
            raise ReferenceDataDeclarationError(
                f"reference row key/value columns overlap: {sorted(overlap)}"
            )
        _validate_wire_values({**key, **values})
        return cls(MappingProxyType(dict(key)), MappingProxyType(dict(values)))

    @property
    def complete_values(self) -> dict[str, Any]:
        return {**self.key, **self.values}


@dataclass(frozen=True)
class ReferenceTable:
    table_name: str
    key_columns: tuple[str, ...]
    managed_prefix_column: str
    managed_prefix: str
    rows: tuple[ReferenceRow, ...]

    def __post_init__(self) -> None:
        if self.table_name not in EXPECTED_V2_TABLES:
            raise ReferenceDataDeclarationError(
                f"unreviewed reference-data table: {self.table_name}"
            )
        if not self.key_columns or self.managed_prefix_column not in self.key_columns:
            raise ReferenceDataDeclarationError(
                "managed prefix column must be part of the stable key"
            )
        seen_keys: set[tuple[Any, ...]] = set()
        for row in self.rows:
            if tuple(row.key) != self.key_columns:
                raise ReferenceDataDeclarationError(
                    f"{self.table_name} row key columns must be {self.key_columns}"
                )
            prefix_value = row.key[self.managed_prefix_column]
            if not isinstance(prefix_value, str) or not prefix_value.startswith(
                self.managed_prefix
            ):
                raise ReferenceDataDeclarationError(
                    f"{self.table_name} managed key is outside its declared scope"
                )
            stable_key = tuple(row.key[column] for column in self.key_columns)
            if stable_key in seen_keys:
                raise ReferenceDataDeclarationError(
                    f"duplicate reference-data key for {self.table_name}: {stable_key}"
                )
            seen_keys.add(stable_key)


def _validate_wire_values(values: Any) -> None:
    if values is None or isinstance(values, str | int | float | bool):
        return
    if isinstance(values, list | tuple):
        for value in values:
            _validate_wire_values(value)
        return
    if isinstance(values, dict):
        if not all(isinstance(key, str) for key in values):
            raise ReferenceDataDeclarationError(
                "reference-data object keys must be strings"
            )
        for value in values.values():
            _validate_wire_values(value)
        return
    raise ReferenceDataDeclarationError(
        f"unsupported reference-data value type: {type(values).__name__}"
    )


REFERENCE_DATA = (
    ReferenceTable(
        table_name="tax_benefit_models",
        key_columns=("name",),
        managed_prefix_column="name",
        managed_prefix="stage8-",
        rows=(
            ReferenceRow.create(
                key={"name": "stage8-platform-validation"},
                values={
                    "id": VALIDATION_MODEL_ID,
                    "description": (
                        "Stage 8 migration lifecycle validation; canonical "
                        "metadata is introduced in Stage 9."
                    ),
                    "created_at": VALIDATION_TIMESTAMP,
                    "updated_at": VALIDATION_TIMESTAMP,
                },
            ),
        ),
    ),
    ReferenceTable(
        table_name="tax_benefit_model_versions",
        key_columns=("model_id", "version"),
        managed_prefix_column="version",
        managed_prefix="stage8-",
        rows=(
            ReferenceRow.create(
                key={
                    "model_id": VALIDATION_MODEL_ID,
                    "version": "stage8-platform-validation",
                },
                values={
                    "id": VALIDATION_MODEL_VERSION_ID,
                    "description": ("Stage 8 generated data-migration validation row."),
                    "created_at": VALIDATION_TIMESTAMP,
                },
            ),
        ),
    ),
)
