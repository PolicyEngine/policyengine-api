"""Strict HTTP response models for API v2 metadata resources."""

from __future__ import annotations

from typing import Annotated, Generic, Literal, TypeVar

from pydantic import StringConstraints

from policyengine_api.data.v2.metadata.reads import (
    MetadataCanonicalParameterValue,
    MetadataDataset,
    MetadataDetailResult,
    MetadataEconomyOptionsResult,
    MetadataModel,
    MetadataModelSelectionResult,
    MetadataModelVersionDetail,
    MetadataPageResult,
    MetadataParameterChild,
    MetadataParameterSummary,
    MetadataRegion,
    MetadataVariable,
    StrictResponseModel,
)


ResourceT = TypeVar("ResourceT")


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
