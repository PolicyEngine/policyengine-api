"""Framework-independent field types shared by user association resources."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import TYPE_CHECKING, Annotated, Protocol, TypeAlias, Union

from pydantic import BaseModel, ConfigDict, FiniteFloat, StringConstraints
from typing_extensions import TypeAliasType

from policyengine_api.services.v2.legacy_refs.types import LegacyRecordKind


ASSOCIATION_DESCRIPTION_MAX_LENGTH = 10_000

# A JSON value without NaN or Infinity. Python's JSON parser accepts both, but
# Postgres JSONB rejects them, so they must fail request validation instead.
# Type checkers get the plain recursive alias (as Pydantic's own JsonValue
# does); Pydantic needs TypeAliasType to build the recursive validator.
if TYPE_CHECKING:
    FiniteJsonValue: TypeAlias = Union[
        list["FiniteJsonValue"],
        dict[str, "FiniteJsonValue"],
        str,
        bool,
        int,
        float,
        None,
    ]
else:
    FiniteJsonValue = TypeAliasType(
        "FiniteJsonValue",
        Union[
            list["FiniteJsonValue"],
            dict[str, "FiniteJsonValue"],
            str,
            bool,
            int,
            FiniteFloat,
            None,
        ],
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
    ) -> dict[LegacyRecordKind, frozenset[int]]: ...

    def require_existing(
        self,
        *,
        country_id: str,
        requested: Mapping[LegacyRecordKind, Collection[int]],
    ) -> None: ...
