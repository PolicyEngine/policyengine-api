"""Framework-independent field types shared by user association resources."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Protocol, TypeAlias

from pydantic import BaseModel, ConfigDict, FiniteFloat, StringConstraints
from typing_extensions import TypeAliasType

ASSOCIATION_DESCRIPTION_MAX_LENGTH = 10_000

# A JSON value without NaN or Infinity. Python's JSON parser accepts both, but
# Postgres JSONB rejects them, so they must fail request validation instead.
# Type checkers get the plain recursive alias (as Pydantic's own JsonValue
# does); Pydantic needs TypeAliasType to build the recursive validator.
if TYPE_CHECKING:
    from collections.abc import Collection, Mapping
    from uuid import UUID

    from policyengine_api.services.v2.legacy_refs.types import LegacyRecordKind

    FiniteJsonValue: TypeAlias = (
        list["FiniteJsonValue"]
        | dict[str, "FiniteJsonValue"]
        | str
        | bool
        | int
        | float
        | None
    )
else:
    FiniteJsonValue = TypeAliasType(
        "FiniteJsonValue",
        list["FiniteJsonValue"]
        | dict[str, "FiniteJsonValue"]
        | str
        | bool
        | int
        | FiniteFloat
        | None,
    )

AssociationName = Annotated[str, StringConstraints(max_length=255)]
AssociationDescription = Annotated[
    str, StringConstraints(max_length=ASSOCIATION_DESCRIPTION_MAX_LENGTH)
]


class StrictAssociationModel(BaseModel):
    """Reject fields outside a reviewed association contract.

    Float fields also reject NaN and Infinity, which Postgres cannot store.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class LegacyReferenceChecker(Protocol):
    """Read-only v1 existence checks performed before a v2 transaction."""

    def existing_ids(
        self,
        *,
        country_id: str,
        requested: Mapping[LegacyRecordKind, Collection[int]],
    ) -> dict[LegacyRecordKind, frozenset[int]]:
        """Return, for every requested kind, the IDs that exist in this country."""
        ...

    def require_existing(
        self,
        *,
        country_id: str,
        requested: Mapping[LegacyRecordKind, Collection[int]],
    ) -> None:
        """Raise ``LegacyReferenceNotFoundError`` if any requested ID is missing."""
        ...


class SimulationReferenceChecker(Protocol):
    """Existence checks of v2 reports and simulations, run before a v2 transaction.

    Both raise ``SimulationReferenceNotFoundError`` when the simulation service
    has no such record in the country, and ``SimulationServiceUnavailableError``
    when it cannot be asked.
    """

    def require_report(
        self,
        *,
        country_id: str,
        report_id: UUID,
        legacy_report_id: int | None = None,
    ) -> None:
        """Raise unless the country has the report.

        With ``legacy_report_id``, also raise ``AssociationReferenceConflictError``
        unless the report was migrated from that v1 report output.
        """
        ...

    def require_simulation(self, *, country_id: str, simulation_id: UUID) -> None:
        """Raise unless the country has the simulation."""
        ...
