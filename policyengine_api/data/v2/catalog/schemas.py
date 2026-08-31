"""Typed response schemas for the dormant v2 metadata preview."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue, StringConstraints


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


class MetadataResourceSuccessResponse(StrictResponseModel, Generic[ResourceT]):
    status: Literal["ok"] = "ok"
    message: None = None
    result: ResourceT


class MetadataModelPageResponse(
    MetadataResourceSuccessResponse[MetadataPageResult[MetadataModel]]
):
    pass


class MetadataModelDetailResponse(
    MetadataResourceSuccessResponse[MetadataDetailResult[MetadataModel]]
):
    pass


class MetadataModelSelectionResponse(
    MetadataResourceSuccessResponse[MetadataModelSelectionResult]
):
    pass


class MetadataModelVersionPageResponse(
    MetadataResourceSuccessResponse[MetadataPageResult[MetadataModelVersionDetail]]
):
    pass


class MetadataModelVersionDetailResponse(
    MetadataResourceSuccessResponse[MetadataDetailResult[MetadataModelVersionDetail]]
):
    pass


class MetadataVariablePageResponse(
    MetadataResourceSuccessResponse[MetadataPageResult[MetadataVariable]]
):
    pass


class MetadataVariableDetailResponse(
    MetadataResourceSuccessResponse[MetadataDetailResult[MetadataVariable]]
):
    pass


class MetadataParameterPageResponse(
    MetadataResourceSuccessResponse[MetadataPageResult[MetadataParameterSummary]]
):
    pass


class MetadataParameterDetailResponse(
    MetadataResourceSuccessResponse[MetadataDetailResult[MetadataParameterSummary]]
):
    pass


class MetadataParameterChildPageResponse(
    MetadataResourceSuccessResponse[MetadataPageResult[MetadataParameterChild]]
):
    pass


class MetadataParameterValuePageResponse(
    MetadataResourceSuccessResponse[MetadataPageResult[MetadataCanonicalParameterValue]]
):
    pass


class MetadataParameterValueDetailResponse(
    MetadataResourceSuccessResponse[
        MetadataDetailResult[MetadataCanonicalParameterValue]
    ]
):
    pass


class MetadataDatasetPageResponse(
    MetadataResourceSuccessResponse[MetadataPageResult[MetadataDataset]]
):
    pass


class MetadataDatasetDetailResponse(
    MetadataResourceSuccessResponse[MetadataDetailResult[MetadataDataset]]
):
    pass


class MetadataRegionPageResponse(
    MetadataResourceSuccessResponse[MetadataPageResult[MetadataRegion]]
):
    pass


class MetadataRegionDetailResponse(
    MetadataResourceSuccessResponse[MetadataDetailResult[MetadataRegion]]
):
    pass


class MetadataEconomyOptionsResponse(
    MetadataResourceSuccessResponse[MetadataEconomyOptionsResult]
):
    pass


class MetadataErrorResponse(StrictResponseModel):
    status: Literal["error"] = "error"
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
