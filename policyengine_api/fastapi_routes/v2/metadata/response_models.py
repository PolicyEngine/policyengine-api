"""Strict HTTP response models for API v2 metadata resources."""

from __future__ import annotations

from datetime import date
from typing import Generic, Literal, TypeVar

from policyengine_api.services.v2.metadata.types import (
    MetadataCanonicalParameterValue,
    MetadataCatalogParametersResult,
    MetadataCatalogVariablesResult,
    MetadataDataset,
    MetadataDetailResult,
    MetadataEconomyOptionsResult,
    MetadataModel,
    MetadataModelCatalogResult,
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


class MetadataModelCatalogResponse(
    MetadataResourceSuccessResponse[MetadataModelCatalogResult]
):
    """Success response holding the small parts of one catalog version."""


class MetadataCatalogVariablesResponse(
    MetadataResourceSuccessResponse[MetadataCatalogVariablesResult]
):
    """Success response holding every variable of one catalog version."""


class MetadataCatalogParametersResponse(
    MetadataResourceSuccessResponse[MetadataCatalogParametersResult]
):
    """Success response holding parameters fetched by name, with their values."""


class MetadataParameterSearchFileEditabilityChange(StrictResponseModel):
    """From ``start_date`` (an ISO date), whether a draft can edit the value."""

    start_date: date
    editable: bool


class MetadataParameterSearchFileParameter(StrictResponseModel):
    """A parameter a reform can change, with what v3's search indexes.

    ``label`` is the stored label, or null when none is stored. ``editable``
    says whether a draft can edit the earliest current-law value (a number, a
    yes/no value or an infinite threshold); ``editable_changes``, when
    present, lists the dates from which that changes.
    """

    path: str
    label: str | None
    unit: str | None
    description: str | None
    editable: bool
    editable_changes: list[MetadataParameterSearchFileEditabilityChange] | None = None


class MetadataParameterSearchFileLabel(StrictResponseModel):
    """Another parameter under ``gov``: its path and stored label, or null."""

    path: str
    label: str | None


class MetadataParameterSearchFileNode(StrictResponseModel):
    """A node under ``gov`` that has a stored label."""

    path: str
    label: str


class MetadataParameterSearchFileContent(StrictResponseModel):
    """One catalog version's parameter search file, ordered by path.

    It holds what v3's parameter search reads, without the catalog's values.
    A reader applies v1's label fallback where a label is null.
    """

    format: int
    country_id: str
    policyengine_version: str
    parameters: list[MetadataParameterSearchFileParameter]
    other_parameters: list[MetadataParameterSearchFileLabel]
    nodes: list[MetadataParameterSearchFileNode]
