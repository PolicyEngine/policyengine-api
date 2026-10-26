"""Framework-independent data exchanged by v2 metadata layers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Generic, Literal, NamedTuple, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue

if TYPE_CHECKING:
    from policyengine_api.data.v2.models import Parameter


@dataclass(frozen=True)
class ParameterFilter:
    """Which parameters a listing keeps.

    ``search`` keeps parameters whose name, label or description contains it,
    ignoring case, and ``names`` the parameters with those exact names.
    """

    search: str | None = None
    names: tuple[str, ...] | None = None


@dataclass(frozen=True)
class ParameterValueFilter:
    """Which current-law parameter values a listing keeps.

    ``parameter_id`` keeps one parameter's values, ``parameter_names`` the
    values of the parameters with those exact names, and ``current`` the values
    in effect on the UTC day of ``now`` (today when ``now`` is None).
    """

    parameter_id: UUID | None = None
    current: bool = False
    now: datetime | None = None
    parameter_names: tuple[str, ...] | None = None


@dataclass(frozen=True)
class ParameterValueSelection:
    """The parameters and effective day a parameter-value read is narrowed to.

    None for any of them leaves the read unnarrowed by it.
    """

    parameter_id: UUID | None
    selected_day: datetime | None
    parameter_names: tuple[str, ...] | None = None


class CurrentLawValueRow(NamedTuple):
    """One current-law value of a parameter, read with the parameter's name."""

    name: str
    value_json: Any
    start_date: datetime
    end_date: datetime | None


@dataclass(frozen=True)
class FoundParameters:
    """The stored parameters a by-name read found, and their names."""

    parameters: list[Parameter]
    names: set[str]


class ParameterNodeLabelRow(NamedTuple):
    """A parameter node's name and its stored label (None when it has none)."""

    name: str
    label: str | None


class StrictResponseModel(BaseModel):
    """Base for metadata results that rejects unknown fields and non-finite numbers."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class MetadataRegionType(StrEnum):
    """The geographic level of a region."""

    NATIONAL = "national"
    COUNTRY = "country"
    STATE = "state"
    CONGRESSIONAL_DISTRICT = "congressional_district"
    CONSTITUENCY = "constituency"
    LOCAL_AUTHORITY = "local_authority"
    CITY = "city"
    PLACE = "place"


class MetadataModel(StrictResponseModel):
    """A country's tax-benefit model in the selected PolicyEngine.py catalog."""

    id: UUID
    name: str
    description: str | None


class MetadataModelVersion(StrictResponseModel):
    """One published version of a country's tax-benefit model."""

    id: UUID
    model_id: UUID
    version: str
    description: str | None


class MetadataEnumValue(StrictResponseModel):
    """One value of an enum variable: its stored name and its display label.

    The label keeps the type the country package declares it with.
    """

    value: str
    label: str | int | float | bool | None


class MetadataVariable(StrictResponseModel):
    """A variable the tax-benefit model computes or accepts as input.

    adds and subtracts, when present, list the variables summed into or
    subtracted from this one. When the model takes that list from a
    parameter, adds_parameter_path or subtracts_parameter_path names the
    parameter, whose dated values give the list for each year (adds and
    subtracts hold its value on 2025-01-01). The catalog format 2 fields
    (is_input_variable, hidden_input, module_name, the two parameter paths
    and enum_values) are null in versions published before that format.
    """

    id: UUID
    name: str
    label: str | None
    entity: str
    description: str | None
    data_type: str | None
    possible_values: list[str] | None
    default_value: JsonValue
    adds: list[str] | None
    subtracts: list[str] | None
    is_input_variable: bool | None = None
    hidden_input: bool | None = None
    module_name: str | None = None
    adds_parameter_path: str | None = None
    subtracts_parameter_path: str | None = None
    enum_values: list[MetadataEnumValue] | None = None


class MetadataParameterSummary(StrictResponseModel):
    """A policy parameter, described without its values.

    Its current-law values are listed by GET /v2/parameter-values. economy and
    household say whether a reform of an economy or of a household may change
    it; they are null in versions published before catalog format 2.
    """

    id: UUID
    name: str
    label: str | None
    description: str | None
    data_type: str | None
    unit: str | None
    economy: bool | None = None
    household: bool | None = None


class MetadataCanonicalParameterValue(StrictResponseModel):
    """One current-law value of a parameter.

    The value applies from start_date until end_date, or indefinitely when
    end_date is null.
    """

    id: UUID
    parameter_id: UUID
    value: JsonValue
    start_date: datetime
    end_date: datetime | None


class MetadataDataset(StrictResponseModel):
    """A named input dataset available to the selected model version.

    These datasets are logical inputs, so storage_path is always null and
    is_output_dataset is always false.
    """

    id: UUID
    name: str
    description: str | None
    year: int
    storage_path: None = None
    is_output_dataset: Literal[False] = False


class MetadataRegion(StrictResponseModel):
    """A region the model can simulate, such as a country, state or constituency.

    When requires_filter is true, filter_strategy says how the region selects
    households of its default dataset. With "row_filter", it keeps the
    households whose filter_field column equals filter_value (or is in it,
    when filter_value is a JSON list).
    """

    id: UUID
    code: str
    label: str
    region_type: MetadataRegionType
    requires_filter: bool
    filter_field: str | None
    filter_value: str | None
    filter_strategy: str | None
    parent_code: str | None
    state_code: str | None
    state_name: str | None
    default_dataset_id: UUID


class MetadataRegionOption(StrictResponseModel):
    """A region that can be chosen for an economy calculation; name is its code."""

    name: str
    label: str
    type: MetadataRegionType


class MetadataTimePeriodOption(StrictResponseModel):
    """A year that can be chosen for an economy calculation."""

    name: int
    label: str


class MetadataDatasetOption(StrictResponseModel):
    """The national dataset, offered as the default for an economy calculation."""

    name: str
    label: str
    default: Literal[True] = True


class MetadataModelVersionDetail(MetadataModelVersion):
    """A model version, with its current-law policy id and the years offered."""

    current_law_id: int
    metadata_time_periods: list[int]


class MetadataParameterChild(StrictResponseModel):
    """A direct child in the parameter tree.

    A node has a child_count; a parameter leaf carries the parameter's summary.
    """

    path: str
    label: str
    type: Literal["node", "parameter"]
    child_count: int | None = None
    parameter: MetadataParameterSummary | None = None


ResourceT = TypeVar("ResourceT")


class MetadataPageResult(StrictResponseModel, Generic[ResourceT]):
    """One page of a metadata collection; has_more says whether a later page exists."""

    policyengine_version: str
    items: list[ResourceT]
    offset: int
    limit: int
    has_more: bool


class MetadataDetailResult(StrictResponseModel, Generic[ResourceT]):
    """One metadata item, with the PolicyEngine.py version it was read from."""

    policyengine_version: str
    item: ResourceT


class MetadataModelSelectionResult(StrictResponseModel):
    """A country's model together with the model version selected for the request."""

    policyengine_version: str
    model: MetadataModel
    model_version: MetadataModelVersionDetail


class MetadataEconomyOptionsResult(StrictResponseModel):
    """The choices for configuring an economy calculation.

    It lists the selectable regions, years and datasets, and the id of the
    current-law policy to use as a baseline.
    """

    policyengine_version: str
    current_law_id: int
    region: list[MetadataRegionOption]
    time_period: list[MetadataTimePeriodOption]
    datasets: list[MetadataDatasetOption]


class MetadataEntity(StrictResponseModel):
    """A kind of member a household holds, such as a person or a tax unit.

    plural is the key the household's members of this kind are listed under,
    and is_person marks the entity every household input about a person uses.
    """

    key: str
    plural: str
    is_person: bool


class MetadataEconomyOptions(StrictResponseModel):
    """The region, year and dataset choices for an economy calculation.

    Every list is empty for a catalog without regions, such as a
    household-only country's, which offers no economy calculation.
    """

    region: list[MetadataRegionOption]
    time_period: list[MetadataTimePeriodOption]
    datasets: list[MetadataDatasetOption]


class MetadataModelCatalogResult(StrictResponseModel):
    """The small parts of one catalog version, read when a client starts.

    policyengine_version names the selected catalog version, so a client can
    request its other parts for that exact version. catalog_format is null,
    and entities and basic_inputs are empty, for a version published before
    catalog format 2. Variables, parameters and their values are served by
    their own routes.
    """

    policyengine_version: str
    catalog_format: int | None
    model: MetadataModel
    model_version: MetadataModelVersionDetail
    entities: list[MetadataEntity]
    basic_inputs: list[str]
    regions: list[MetadataRegion]
    datasets: list[MetadataDataset]
    economy_options: MetadataEconomyOptions


class MetadataDatedValue(StrictResponseModel):
    """A current-law parameter value from start_date until end_date.

    A null end_date means the value applies until a later value starts, or
    indefinitely.
    """

    start_date: datetime
    end_date: datetime | None
    value: JsonValue


class MetadataCatalogVariablesResult(StrictResponseModel):
    """Every variable of one catalog version, in name order.

    part_parameter_values has an entry for each parameter path a variable's
    adds_parameter_path or subtracts_parameter_path names: that parameter's
    current-law values in start-date order, or an empty list when the
    catalog has no such parameter.
    """

    policyengine_version: str
    catalog_format: int | None
    variables: list[MetadataVariable]
    part_parameter_values: dict[str, list[MetadataDatedValue]]


class MetadataCatalogParameter(MetadataParameterSummary):
    """A parameter with its current-law values in start-date order."""

    values: list[MetadataDatedValue]


class MetadataCatalogParametersResult(StrictResponseModel):
    """Requested parameters of one catalog version, in name order.

    node_labels maps each ancestor of a requested parameter that the version
    stores as a parameter node to the node's stored label (null when it has
    none), for breadcrumbs; a bracket index such as ``rates[0]`` counts as a
    child of its schedule ``rates``. missing_names lists requested names the
    version has no parameter for.
    """

    policyengine_version: str
    catalog_format: int | None
    parameters: list[MetadataCatalogParameter]
    node_labels: dict[str, str | None]
    missing_names: list[str]
