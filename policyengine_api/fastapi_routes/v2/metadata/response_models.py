"""Strict HTTP response models for API v2 metadata resources."""

from __future__ import annotations

from typing import Generic, Literal, TypeVar

from policyengine_api.services.v2.metadata.types import (
    MetadataCanonicalParameterValue,
    MetadataCatalogResult,
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
    """Success envelope: ``status`` "ok", a null ``message`` and the ``result``."""

    status: Literal["ok"] = "ok"
    message: None = None
    result: ResourceT


class MetadataModelPageResponse(
    MetadataResourceSuccessResponse[MetadataPageResult[MetadataModel]]
):
    """Success response holding a page of the selected catalog's tax-benefit models.

    A catalog has one model per country, so only the first page has an item.
    """


class MetadataModelDetailResponse(
    MetadataResourceSuccessResponse[MetadataDetailResult[MetadataModel]]
):
    """Success response holding one tax-benefit model."""


class MetadataModelSelectionResponse(
    MetadataResourceSuccessResponse[MetadataModelSelectionResult]
):
    """Success response holding a country's model and its selected model version."""


class MetadataModelVersionPageResponse(
    MetadataResourceSuccessResponse[MetadataPageResult[MetadataModelVersionDetail]]
):
    """Success response holding a page of the selected catalog's model versions.

    A catalog has one model version, so only the first page has an item.
    """


class MetadataModelVersionDetailResponse(
    MetadataResourceSuccessResponse[MetadataDetailResult[MetadataModelVersionDetail]]
):
    """Success response holding one model version."""


class MetadataVariablePageResponse(
    MetadataResourceSuccessResponse[MetadataPageResult[MetadataVariable]]
):
    """Success response holding one page of variables."""


class MetadataVariableDetailResponse(
    MetadataResourceSuccessResponse[MetadataDetailResult[MetadataVariable]]
):
    """Success response holding one variable."""


class MetadataParameterPageResponse(
    MetadataResourceSuccessResponse[MetadataPageResult[MetadataParameterSummary]]
):
    """Success response holding one page of parameters."""


class MetadataParameterDetailResponse(
    MetadataResourceSuccessResponse[MetadataDetailResult[MetadataParameterSummary]]
):
    """Success response holding one parameter."""


class MetadataParameterChildPageResponse(
    MetadataResourceSuccessResponse[MetadataPageResult[MetadataParameterChild]]
):
    """Success response holding one page of a parameter path's direct children."""


class MetadataParameterValuePageResponse(
    MetadataResourceSuccessResponse[MetadataPageResult[MetadataCanonicalParameterValue]]
):
    """Success response holding one page of parameter values."""


class MetadataParameterValueDetailResponse(
    MetadataResourceSuccessResponse[
        MetadataDetailResult[MetadataCanonicalParameterValue]
    ]
):
    """Success response holding one parameter value."""


class MetadataDatasetPageResponse(
    MetadataResourceSuccessResponse[MetadataPageResult[MetadataDataset]]
):
    """Success response holding one page of datasets."""


class MetadataDatasetDetailResponse(
    MetadataResourceSuccessResponse[MetadataDetailResult[MetadataDataset]]
):
    """Success response holding one dataset."""


class MetadataRegionPageResponse(
    MetadataResourceSuccessResponse[MetadataPageResult[MetadataRegion]]
):
    """Success response holding one page of regions."""


class MetadataRegionDetailResponse(
    MetadataResourceSuccessResponse[MetadataDetailResult[MetadataRegion]]
):
    """Success response holding one region."""


class MetadataEconomyOptionsResponse(
    MetadataResourceSuccessResponse[MetadataEconomyOptionsResult]
):
    """Success response holding the options for configuring an economy comparison."""


class MetadataCatalogResponse(MetadataResourceSuccessResponse[MetadataCatalogResult]):
    """Success response holding a whole catalog version's parameters and variables."""
