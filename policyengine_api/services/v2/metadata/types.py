"""Framework-independent data exchanged by v2 metadata layers."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue


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


class MetadataVariable(StrictResponseModel):
    """A variable the tax-benefit model computes or accepts as input.

    adds and subtracts, when present, list the variables summed into or
    subtracted from this one.
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


class MetadataParameterSummary(StrictResponseModel):
    """A policy parameter, described without its values.

    Its current-law values are listed by GET /v2/parameter-values.
    """

    id: UUID
    name: str
    label: str | None
    description: str | None
    data_type: str | None
    unit: str | None


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

    When requires_filter is true, the region is simulated by filtering its
    default dataset on filter_field and filter_value.
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
