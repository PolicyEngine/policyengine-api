"""Strict normalized household document schemas shared by HTTP input and output."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    field_validator,
    model_serializer,
)
from pydantic.json_schema import SkipJsonSchema

from policyengine_api.spm import SPMSelection

if TYPE_CHECKING:
    from pydantic import SerializerFunctionWrapHandler

DocumentIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=False, min_length=1, max_length=255),
]
EntityValues = Annotated[dict[str, JsonValue], Field(max_length=500)]


class StrictHouseholdDocumentModel(BaseModel):
    """Base for household document records; rejects unknown keys and NaN or infinity."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class HouseholdEntityRecord(StrictHouseholdDocumentModel):
    """One group entity in a household, such as a tax unit or a benefit unit.

    ``id`` is unique within its collection and is what people's ``memberships``
    refer to. ``values`` maps variable names to values, and ``source_name``
    optionally keeps the entity's original name, such as its key in a v1 household.
    """

    id: DocumentIdentifier
    source_name: DocumentIdentifier | None = None
    values: EntityValues


class HouseholdPersonRecord(HouseholdEntityRecord):
    """One person in a household.

    ``memberships`` maps each of the country's entity collections to the ``id``
    of the group the person belongs to, and must name every collection.
    """

    memberships: dict[str, DocumentIdentifier]


EntityRecords = Annotated[list[HouseholdEntityRecord], Field(max_length=1_000)]
PersonRecords = Annotated[list[HouseholdPersonRecord], Field(max_length=1_000)]


def _omit_spm_default(schema: dict[str, Any]) -> None:
    # Omission preserves historical identity; explicit null is not a selection.
    schema.pop("default", None)


class USHouseholdDocument(StrictHouseholdDocumentModel):
    """US household content: people and the US group entities they belong to.

    ``spm`` optionally selects an SPM forecast scenario and geography; omit it
    rather than sending null.
    """

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
    def require_spm_object(cls, value: object) -> object:
        """Reject an explicit null ``spm``; omit the field to make no selection."""
        if value is None:
            msg = "spm must be an object when supplied"
            raise ValueError(msg)
        return value

    @model_serializer(mode="wrap")
    def serialize_document(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, Any]:
        """Serialize the document, leaving out ``spm`` when no selection was made.

        Omitting the key keeps such documents identical to those stored before
        ``spm`` existed.
        """
        document: dict[str, Any] = handler(self)
        if self.spm is None:
            document.pop("spm", None)
        return document


class UKHouseholdDocument(StrictHouseholdDocumentModel):
    """UK household content: people, households and benefit units."""

    people: PersonRecords
    household: EntityRecords
    benunit: EntityRecords


HouseholdDocument: TypeAlias = USHouseholdDocument | UKHouseholdDocument
