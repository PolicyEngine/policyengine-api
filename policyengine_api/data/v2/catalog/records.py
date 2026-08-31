"""Immutable database-independent records for the v2 metadata catalog."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Any, TypeVar
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ModelRecord:
    id: UUID
    country_id: str
    name: str
    description: str | None


@dataclass(frozen=True, slots=True)
class ModelVersionRecord:
    id: UUID
    model_id: UUID
    version: str
    description: str | None
    current_law_id: int
    metadata_time_periods: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class VariableRecord:
    id: UUID
    model_version_id: UUID
    name: str
    label: str | None
    entity: str
    description: str | None
    data_type: str | None
    possible_values: list[str] | None
    default_value: Any
    adds: list[str] | None
    subtracts: list[str] | None


@dataclass(frozen=True, slots=True)
class ParameterNodeRecord:
    id: UUID
    model_version_id: UUID
    name: str
    label: str | None
    description: str | None


@dataclass(frozen=True, slots=True)
class ParameterValueRecord:
    id: UUID
    parameter_id: UUID
    value_json: Any
    start_date: datetime
    end_date: datetime | None


@dataclass(frozen=True, slots=True)
class ParameterRecord:
    id: UUID
    model_version_id: UUID
    name: str
    label: str | None
    description: str | None
    data_type: str | None
    unit: str | None
    values: tuple[ParameterValueRecord, ...]


@dataclass(frozen=True, slots=True)
class DatasetRecord:
    id: UUID
    model_version_id: UUID
    name: str
    description: str | None
    year: int
    storage_path: None = None
    is_output_dataset: bool = False


@dataclass(frozen=True, slots=True)
class RegionRecord:
    id: UUID
    model_version_id: UUID
    default_dataset_id: UUID
    code: str
    label: str
    region_type: str
    requires_filter: bool
    filter_field: str | None
    filter_value: str | None
    filter_strategy: str | None
    parent_code: str | None
    state_code: str | None
    state_name: str | None


@dataclass(frozen=True, slots=True)
class FallbackSummary:
    region_type: str
    count: int


RecordT = TypeVar("RecordT")


def iter_batches(
    records: Sequence[RecordT],
    *,
    batch_size: int,
) -> Iterator[tuple[RecordT, ...]]:
    """Yield bounded immutable slices without constructing a flattened copy."""

    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    for start in range(0, len(records), batch_size):
        yield tuple(records[start : start + batch_size])


@dataclass(frozen=True, slots=True)
class CountryCatalog:
    country_id: str
    model: ModelRecord
    model_version: ModelVersionRecord
    variables: tuple[VariableRecord, ...]
    parameter_nodes: tuple[ParameterNodeRecord, ...]
    parameters: tuple[ParameterRecord, ...]
    datasets: tuple[DatasetRecord, ...]
    regions: tuple[RegionRecord, ...]
    fallback_summaries: tuple[FallbackSummary, ...]

    def parameter_value_batches(
        self,
        *,
        batch_size: int,
    ) -> Iterator[tuple[ParameterValueRecord, ...]]:
        """Yield canonical parameter values in bounded batches."""

        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        batch: list[ParameterValueRecord] = []
        for parameter in self.parameters:
            for value in parameter.values:
                batch.append(value)
                if len(batch) == batch_size:
                    yield tuple(batch)
                    batch.clear()
        if batch:
            yield tuple(batch)

    def entity_counts(self) -> dict[str, int]:
        """Return non-secret record counts for validation and deployment evidence."""

        return {
            "models": 1,
            "model_versions": 1,
            "variables": len(self.variables),
            "parameter_nodes": len(self.parameter_nodes),
            "parameters": len(self.parameters),
            "parameter_values": sum(
                len(parameter.values) for parameter in self.parameters
            ),
            "datasets": len(self.datasets),
            "regions": len(self.regions),
        }


@dataclass(frozen=True, slots=True)
class NormalizedCatalog:
    policyengine_version: str
    dependency_versions: tuple[tuple[str, str], ...]
    countries: tuple[CountryCatalog, ...]

    def country(self, country_id: str) -> CountryCatalog:
        """Return one supported country catalog."""

        for catalog in self.countries:
            if catalog.country_id == country_id:
                return catalog
        raise KeyError(country_id)

    def entity_counts(self) -> dict[str, int]:
        """Return aggregate counts without catalog content."""

        counts: dict[str, int] = {}
        for country in self.countries:
            for name, count in country.entity_counts().items():
                counts[name] = counts.get(name, 0) + count
        return counts


def record_content(record: object) -> tuple[Any, ...]:
    """Return a deterministic field-ordered representation for comparisons."""

    return tuple(getattr(record, item.name) for item in fields(record))
