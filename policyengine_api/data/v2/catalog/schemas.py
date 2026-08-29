"""Typed response schemas for the dormant v2 metadata preview."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints


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


class MetadataParameterNode(StrictResponseModel):
    id: UUID
    name: str
    label: str | None
    description: str | None


class MetadataParameterValue(StrictResponseModel):
    id: UUID
    value: JsonValue
    start_date: datetime
    end_date: datetime | None


class MetadataParameter(StrictResponseModel):
    id: UUID
    name: str
    label: str | None
    description: str | None
    data_type: str | None
    unit: str | None
    values: list[MetadataParameterValue]


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


class MetadataEconomyOptions(StrictResponseModel):
    region: list[MetadataRegionOption]
    time_period: list[MetadataTimePeriodOption]
    datasets: list[MetadataDatasetOption]


class MetadataResult(StrictResponseModel):
    current_law_id: int
    model: MetadataModel
    model_version: MetadataModelVersion
    variables: list[MetadataVariable]
    parameter_nodes: list[MetadataParameterNode]
    parameters: list[MetadataParameter]
    datasets: list[MetadataDataset]
    regions: list[MetadataRegion]
    economy_options: MetadataEconomyOptions


class MetadataSuccessResponse(StrictResponseModel):
    status: Literal["ok"] = "ok"
    message: None = None
    result: MetadataResult


class MetadataErrorResponse(StrictResponseModel):
    status: Literal["error"] = "error"
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


MetadataPreviewResponse = Annotated[
    MetadataSuccessResponse | MetadataErrorResponse,
    Field(discriminator="status"),
]
