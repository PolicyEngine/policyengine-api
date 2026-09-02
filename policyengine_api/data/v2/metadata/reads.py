"""Shared database reads and typed read results for API v2 metadata."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from policyengine_api.data.v2.catalog.catalog_selection import (
    MetadataCatalogUnavailableError,
    SelectedCatalog,
    select_catalog as select_metadata_catalog,
    validate_policyengine_version,
)


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


class MetadataResourceNotFoundError(LookupError):
    """Raised when a selected catalog does not contain a requested resource."""


class InvalidMetadataPageError(ValueError):
    """Raised when collection pagination is outside the documented bounds."""


class MetadataReadContext:
    """Own the session and catalog selection shared by metadata read methods."""

    def __init__(self, session: Session, *, running_policyengine_version: str):
        self._session = session
        self._running_policyengine_version = validate_policyengine_version(
            running_policyengine_version
        )

    def close(self) -> None:
        """Close the request-owned read session."""

        self._session.close()

    def select_catalog(
        self,
        country_id: str,
        policyengine_version: str | None = None,
    ) -> SelectedCatalog:
        """Select exactly one initialized country catalog."""

        return select_metadata_catalog(
            self._session,
            country_id=country_id,
            running_policyengine_version=self._running_policyengine_version,
            policyengine_version=policyengine_version,
        )

    def _select_paginated_catalog(
        self,
        country_id: str,
        policyengine_version: str | None,
        *,
        offset: int,
        limit: int,
    ) -> SelectedCatalog:
        validate_metadata_page(offset, limit)
        return self.select_catalog(country_id, policyengine_version)


def page_result(
    selected: SelectedCatalog,
    rows: list[ResourceT],
    *,
    offset: int,
    limit: int,
) -> MetadataPageResult[ResourceT]:
    """Return one bounded response page from a limit-plus-one query."""

    return MetadataPageResult(
        policyengine_version=selected.policyengine_version,
        items=rows[:limit],
        offset=offset,
        limit=limit,
        has_more=len(rows) > limit,
    )


def validate_metadata_page(offset: int, limit: int) -> tuple[int, int]:
    """Validate the shared v2 metadata collection bounds."""

    if offset < 0:
        raise InvalidMetadataPageError("offset must be at least 0")
    if not 1 <= limit <= 500:
        raise InvalidMetadataPageError("limit must be between 1 and 500")
    return offset, limit


def query_rows(session: Session, statement: Any) -> list[Any]:
    """Execute one read statement and translate database failures."""

    try:
        return list(session.exec(statement).all())
    except SQLAlchemyError as error:
        raise MetadataCatalogUnavailableError(
            "the v2 metadata catalog cannot be queried"
        ) from error


def escape_like(value: str) -> str:
    """Escape SQL LIKE wildcard characters in a literal search value."""

    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
