"""Immutable database-independent records for the v2 metadata catalog."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from datetime import datetime
    from uuid import UUID


CATALOG_FORMAT = 2
"""The catalog content format this extractor publishes.

Format 2 adds the metadata the app's v3 workspace reads, from PolicyEngine.py's
public records: entities and basic inputs; each variable's input and
hidden-input flags, module, the parameter its ``adds`` or ``subtracts`` names,
and enum value labels; each parameter's economy and household flags. Versions
published before it store null for these fields.
"""


@dataclass(frozen=True, slots=True)
class EntityRecord:
    """A model entity: its key, plural name, and whether it is the person entity."""

    key: str
    plural: str
    is_person: bool


@dataclass(frozen=True, slots=True)
class EnumValueRecord:
    """One value of an enum variable: its stored name and its declared label.

    The label is kept as the country package declares it, usually a string.
    """

    value: str
    label: str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class ModelRecord:
    """One country's tax-benefit model as named in the catalog."""

    id: UUID
    country_id: str
    name: str
    description: str | None


@dataclass(frozen=True, slots=True)
class ModelVersionRecord:
    """The model version a catalog was extracted from.

    Also carries the country's current-law policy id and the years its metadata
    covers.
    """

    id: UUID
    model_id: UUID
    version: str
    description: str | None
    current_law_id: int
    metadata_time_periods: tuple[int, ...]
    catalog_format: int
    entities: tuple[EntityRecord, ...]
    basic_inputs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VariableRecord:
    """One model variable, with its entity, type and the variables it sums.

    ``adds_parameter_path`` and ``subtracts_parameter_path`` name the parameter
    whose dated value lists the variables summed; ``adds`` and ``subtracts``
    keep the list PolicyEngine.py resolved from it.
    """

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
    is_input_variable: bool | None
    hidden_input: bool | None
    module_name: str | None
    adds_parameter_path: str | None
    subtracts_parameter_path: str | None
    enum_values: tuple[EnumValueRecord, ...] | None
    unit: str | None
    definition_period: str | None


@dataclass(frozen=True, slots=True)
class ParameterNodeRecord:
    """A non-leaf node of the parameter tree; it groups parameters and has no values.

    Bracket schedules are nodes too, with their stored label or none.
    """

    id: UUID
    model_version_id: UUID
    name: str
    label: str | None
    description: str | None


@dataclass(frozen=True, slots=True)
class ParameterValueRecord:
    """A parameter's value from ``start_date`` until ``end_date``, or indefinitely."""

    id: UUID
    parameter_id: UUID
    value_json: Any
    start_date: datetime
    end_date: datetime | None


@dataclass(frozen=True, slots=True)
class ParameterRecord:
    """A leaf parameter with its unit and every value it has held over time."""

    id: UUID
    model_version_id: UUID
    name: str
    label: str | None
    description: str | None
    data_type: str | None
    unit: str | None
    values: tuple[ParameterValueRecord, ...]
    economy: bool
    household: bool


@dataclass(frozen=True, slots=True)
class DatasetRecord:
    """A logical input dataset, referenced by name; ``storage_path`` is always None."""

    id: UUID
    model_version_id: UUID
    name: str
    description: str | None
    year: int
    storage_path: None = None
    is_output_dataset: bool = False


@dataclass(frozen=True, slots=True)
class RegionRecord:
    """A region that can be simulated, with the dataset it uses by default.

    Regions that need a subset of that dataset (``requires_filter``) also name
    the variable, value and strategy that select their households.
    """

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
class CertifiedArtifact:
    """One artifact of a country's certified data release, pinned to a revision.

    ``repo_type`` is the Hugging Face repository type, ``model`` or ``dataset``.
    """

    name: str
    repo_id: str
    repo_type: str
    path: str
    revision: str
    sha256: str | None


@dataclass(frozen=True, slots=True)
class FallbackSummary:
    """How many sub-national regions of one type fell back to the default dataset.

    The certified data release names no dataset for their type.
    """

    region_type: str
    count: int


@dataclass(frozen=True, slots=True)
class OmittedRegionSummary:
    """How many reference regions of one type publication left out.

    No scoping rule can select their households yet, such as US places.
    """

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
        msg = "batch_size must be positive"
        raise ValueError(msg)
    for start in range(0, len(records), batch_size):
        yield tuple(records[start : start + batch_size])


@dataclass(frozen=True, slots=True)
class CountryCatalog:
    """Every record the catalog publishes for one country's model version."""

    country_id: str
    model: ModelRecord
    model_version: ModelVersionRecord
    variables: tuple[VariableRecord, ...]
    parameter_nodes: tuple[ParameterNodeRecord, ...]
    parameters: tuple[ParameterRecord, ...]
    datasets: tuple[DatasetRecord, ...]
    regions: tuple[RegionRecord, ...]
    fallback_summaries: tuple[FallbackSummary, ...]
    omitted_region_summaries: tuple[OmittedRegionSummary, ...] = ()
    # The release datasets the regions' row filters read.
    certified_artifacts: tuple[CertifiedArtifact, ...] = ()

    def parameter_value_batches(
        self,
        *,
        batch_size: int,
    ) -> Iterator[tuple[ParameterValueRecord, ...]]:
        """Yield canonical parameter values in bounded batches."""
        if batch_size < 1:
            msg = "batch_size must be positive"
            raise ValueError(msg)
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
    """A complete extracted catalog for one PolicyEngine.py version, all countries."""

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
