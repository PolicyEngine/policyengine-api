"""Framework-neutral read models for API v2 metadata resources."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue


class StrictResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class MetadataRegionType(StrEnum):
    NATIONAL = "national"
    COUNTRY = "country"
    STATE = "state"
    CONGRESSIONAL_DISTRICT = "congressional_district"
    CONSTITUENCY = "constituency"
    LOCAL_AUTHORITY = "local_authority"
    CITY = "city"
    PLACE = "place"


class MetadataModel(StrictResponseModel):
    id: UUID
    name: str
    description: str | None


class MetadataModelVersion(StrictResponseModel):
    id: UUID
    model_id: UUID
    version: str
    description: str | None


class MetadataVariable(StrictResponseModel):
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
    id: UUID
    name: str
    label: str | None
    description: str | None
    data_type: str | None
    unit: str | None


class MetadataCanonicalParameterValue(StrictResponseModel):
    id: UUID
    parameter_id: UUID
    value: JsonValue
    start_date: datetime
    end_date: datetime | None


class MetadataDataset(StrictResponseModel):
    id: UUID
    name: str
    description: str | None
    year: int
    storage_path: None = None
    is_output_dataset: Literal[False] = False


class MetadataRegion(StrictResponseModel):
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
    name: str
    label: str
    type: MetadataRegionType


class MetadataTimePeriodOption(StrictResponseModel):
    name: int
    label: str


class MetadataDatasetOption(StrictResponseModel):
    name: str
    label: str
    default: Literal[True] = True


class MetadataModelVersionDetail(MetadataModelVersion):
    current_law_id: int
    metadata_time_periods: list[int]


class MetadataParameterChild(StrictResponseModel):
    path: str
    label: str
    type: Literal["node", "parameter"]
    child_count: int | None = None
    parameter: MetadataParameterSummary | None = None


ResourceT = TypeVar("ResourceT")


class MetadataPageResult(StrictResponseModel, Generic[ResourceT]):
    policyengine_version: str
    items: list[ResourceT]
    offset: int
    limit: int
    has_more: bool


class MetadataDetailResult(StrictResponseModel, Generic[ResourceT]):
    policyengine_version: str
    item: ResourceT


class MetadataModelSelectionResult(StrictResponseModel):
    policyengine_version: str
    model: MetadataModel
    model_version: MetadataModelVersionDetail


class MetadataEconomyOptionsResult(StrictResponseModel):
    policyengine_version: str
    current_law_id: int
    region: list[MetadataRegionOption]
    time_period: list[MetadataTimePeriodOption]
    datasets: list[MetadataDatasetOption]
