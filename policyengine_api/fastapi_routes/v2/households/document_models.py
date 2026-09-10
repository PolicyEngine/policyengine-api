"""Strict normalized household document schemas shared by HTTP input and output."""

from __future__ import annotations

from typing import Annotated, Any, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    model_serializer,
    field_validator,
)
from pydantic.json_schema import SkipJsonSchema

from policyengine_api.spm import SPMSelection


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


def _omit_spm_default(schema: dict[str, Any]) -> None:
    # Omission preserves historical identity; explicit null is not a selection.
    schema.pop("default", None)


class USHouseholdDocument(StrictHouseholdDocumentModel):
    people: PersonRecords
    household: EntityRecords
    family: EntityRecords
    tax_unit: EntityRecords
    spm_unit: EntityRecords
    marital_unit: EntityRecords
    spm: SPMSelection | SkipJsonSchema[None] = Field(
        default=None, json_schema_extra=_omit_spm_default
    )

    @field_validator("spm", mode="before")
    @classmethod
    def require_spm_object(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("spm must be an object when supplied")
        return value

    @model_serializer(mode="wrap")
    def serialize_document(self, handler: Any) -> dict[str, Any]:
        document: dict[str, Any] = handler(self)
        if self.spm is None:
            document.pop("spm", None)
        return document


class UKHouseholdDocument(StrictHouseholdDocumentModel):
    people: PersonRecords
    household: EntityRecords
    benunit: EntityRecords


HouseholdDocument: TypeAlias = USHouseholdDocument | UKHouseholdDocument
