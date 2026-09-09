"""Strict normalized household document schemas shared by HTTP input and output."""

from __future__ import annotations

from typing import Annotated, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints


DocumentIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=False, min_length=1, max_length=255),
]
EntityValues = Annotated[dict[str, JsonValue], Field(max_length=500)]


class StrictHouseholdDocumentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class HouseholdEntityRecord(StrictHouseholdDocumentModel):
    id: DocumentIdentifier
    source_name: DocumentIdentifier | None = None
    values: EntityValues


class HouseholdPersonRecord(HouseholdEntityRecord):
    memberships: dict[str, DocumentIdentifier]


EntityRecords = Annotated[list[HouseholdEntityRecord], Field(max_length=1_000)]
PersonRecords = Annotated[list[HouseholdPersonRecord], Field(max_length=1_000)]


class USHouseholdDocument(StrictHouseholdDocumentModel):
    people: PersonRecords
    household: EntityRecords
    family: EntityRecords
    tax_unit: EntityRecords
    spm_unit: EntityRecords
    marital_unit: EntityRecords


class UKHouseholdDocument(StrictHouseholdDocumentModel):
    people: PersonRecords
    household: EntityRecords
    benunit: EntityRecords


HouseholdDocument: TypeAlias = USHouseholdDocument | UKHouseholdDocument
