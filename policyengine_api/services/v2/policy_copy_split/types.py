"""Framework-independent data exchanged by the layers of the policy copy split.

A policy copy here is a stored v2 policy that sets a model assumption
(``policyengine_api.dynamic_parameters``): the v1-to-v2 copy made such
policies before it split model assumptions off (C1 · 36), and for UK
``gov.dynamic.`` values until that prefix joined (C1 · 48).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from policyengine_api.services.v2.dynamics.types import (
        ResolvedDynamicCreationInput,
    )
    from policyengine_api.services.v2.policies.types import (
        ResolvedPolicyCreationInput,
    )


class PolicyCopyOutcome(StrEnum):
    """What happens to the old copy once its split is stored."""

    # Nothing names it any more, so it is deleted with its values.
    DELETED = "deleted"
    # A simulation, report or household calculation still names it, so it is
    # kept, although its legacy mappings and saved policies are re-pointed.
    KEPT = "kept"
    # It can't be split as decided, so nothing changes for it.
    REFUSED = "refused"


class PolicyCopyRefusalReason(StrEnum):
    """Why a copy is refused: a mapping's dynamic can't take its assumptions."""

    # The mapping's dynamic sets one of the copy's assumptions, for the same
    # start date, to another value or end date.
    CONFLICTING_DYNAMIC_VALUES = "conflicting_dynamic_values"
    # The mapping's dynamic is bound to another model or catalog version.
    DYNAMIC_ON_ANOTHER_CATALOG = "dynamic_on_another_catalog"
    # Together they hold more values than a dynamic may.
    TOO_MANY_VALUES = "too_many_values"


@dataclass(frozen=True)
class StoredPolicySplit:
    """A stored copy's values, split on its own catalog version.

    ``policy`` holds the values that aren't model assumptions, and may be
    empty; ``dynamic`` holds the model assumptions.
    """

    policy: ResolvedPolicyCreationInput
    dynamic: ResolvedDynamicCreationInput


@dataclass(frozen=True)
class MappingTarget:
    """A legacy mapping naming the copy, and the dynamic it will name.

    ``previous_dynamic_id`` is read before the mapping changes.
    """

    mapping_id: UUID
    country_id: str
    legacy_policy_id: int
    previous_dynamic_id: UUID | None
    dynamic: ResolvedDynamicCreationInput


@dataclass(frozen=True)
class SavedPolicyTarget:
    """A saved policy naming the copy, and the dynamic its saved dynamic will name."""

    user_policy_id: UUID
    user_id: UUID
    country_id: str
    name: str | None
    dynamic: ResolvedDynamicCreationInput


@dataclass(frozen=True)
class PreparedPolicyCopySplit:
    """Everything the split of one copy reads before it writes anything.

    ``refusal_reason`` is set when the copy can't be split; the targets are
    then empty.
    """

    policy_id: UUID
    country_id: str
    policyengine_version: str
    split: StoredPolicySplit
    mapping_targets: tuple[MappingTarget, ...]
    saved_policy_targets: tuple[SavedPolicyTarget, ...]
    references: CopyReferences
    refusal_reason: PolicyCopyRefusalReason | None


@dataclass(frozen=True)
class SplitContent:
    """A policy or dynamic the split points a row at, found by its content hash.

    ``id`` is the stored row's ID. It is None only in a read-only listing,
    for a row that doesn't exist yet. ``created`` says whether this run
    created the row, or in a listing would.
    """

    id: UUID | None
    content_hash: str
    created: bool


@dataclass(frozen=True)
class CopyReferences:
    """How many simulations, reports and household calculations name a copy."""

    simulations: int
    reports: int
    household_jobs: int

    @property
    def total(self) -> int:
        """All three counts together; any of them keeps the copy."""
        return self.simulations + self.reports + self.household_jobs


@dataclass(frozen=True)
class RepointedMapping:
    """A legacy policy mapping moved from the old copy to its split.

    ``previous_dynamic_id`` is the dynamic the mapping named before; when it
    named one, ``dynamic`` holds that dynamic's values and the copy's model
    assumptions together.
    """

    country_id: str
    legacy_policy_id: int
    previous_dynamic_id: UUID | None
    dynamic: SplitContent


@dataclass(frozen=True)
class RepointedSavedPolicy:
    """A saved policy moved from the old copy to its split, and its saved dynamic.

    The saved dynamic belongs to the saved policy's owner, names ``dynamic``
    and takes the saved policy's name. ``saved_dynamic_created`` is false when
    the owner already had an identical one, which is then reused.
    ``saved_dynamic_id`` is None only in a listing, for one that doesn't
    exist yet.
    """

    user_policy_id: UUID
    dynamic: SplitContent
    saved_dynamic_id: UUID | None
    saved_dynamic_created: bool


@dataclass(frozen=True)
class PolicyCopySplit:
    """What the split did to one stored copy, or in a listing would do.

    ``applied`` is false for a read-only listing. ``policy`` and ``dynamic``
    are the plain split of the copy, None only when it is refused.
    """

    old_policy_id: UUID
    country_id: str
    policyengine_version: str
    applied: bool
    outcome: PolicyCopyOutcome
    policy: SplitContent | None
    dynamic: SplitContent | None
    mappings: tuple[RepointedMapping, ...]
    saved_policies: tuple[RepointedSavedPolicy, ...]
    references: CopyReferences
    refusal_reason: PolicyCopyRefusalReason | None


@dataclass(frozen=True)
class SavedDynamicIdentity:
    """What makes two saved dynamics identical: owner, country, dynamic and name."""

    user_id: UUID
    country_id: str
    dynamic_content_hash: str
    name: str | None


@dataclass
class ListedRows:
    """What a listing has reported so far, across copies, by content hash.

    Applying commits each copy before the next, so a later copy finds the
    policies, dynamics and saved dynamics an earlier copy created; the
    listing reports those as found, as applying will.
    """

    policies: dict[str, SplitContent] = field(default_factory=dict)
    dynamics: dict[str, SplitContent] = field(default_factory=dict)
    saved_dynamics: set[SavedDynamicIdentity] = field(default_factory=set)
