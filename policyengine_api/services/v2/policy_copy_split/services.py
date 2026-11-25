"""Split stored policies that set model assumptions into a policy and a dynamic.

The v1-to-v2 copy kept a v1 policy's model assumptions in its v2 policy until
C1 · 36, and UK ``gov.dynamic.`` values until C1 · 48, and a v1 policy is
never copied again. For each stored policy that sets a model assumption
(``policyengine_api.dynamic_parameters``), the split:

- finds or creates the policy without the assumptions (empty when the copy
  set nothing else) and the dynamic holding them, on the copy's own catalog
  version, through C1 · 36's ``create_resolved_policy`` and
  ``create_resolved_dynamic``;
- points each legacy mapping that names the copy at them. A mapping that
  already names a dynamic gets one dynamic holding that dynamic's values and
  the copy's assumptions together;
- points each saved policy that names the copy at the policy, and gives its
  owner a saved dynamic with the saved policy's name and no description,
  naming the dynamic its v1 policy's mapping now names (or the copy's own
  dynamic), unless the owner already has an identical one;
- deletes the copy, its values with it, once nothing names it. A copy that a
  simulation, report or household calculation names is kept: their keys
  hash the policy, and deleting it would set their policy to null.

A copy whose mapping's dynamic can't take its assumptions is refused, and
nothing changes for it. ``scripts/split_v2_policy_copies.py`` runs this as a
temporary role (C1 · 49), and D4 · 1's migration reuses
``split_policy_copy_in_session``. The user's decisions are recorded in
``docs/migration/stage-10-v2-policies.md``.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from policyengine_api.dynamic_parameters import DYNAMIC_PARAMETER_PREFIXES
from policyengine_api.services.v2.dynamics.database_connectors.reads import (
    read_dynamic_by_content_identity,
    read_dynamic_parameter_values,
    read_dynamic_row,
)
from policyengine_api.services.v2.policies.database_connectors.reads import (
    read_model_version,
    read_parameter_values_with_names,
    read_policy_by_content_identity,
)
from policyengine_api.services.v2.policies.transformations import (
    canonicalize_policy,
    stored_policy_creation_input,
)
from policyengine_api.services.v2.policy_copy_split.database_connectors.deletes import (
    delete_policy,
)
from policyengine_api.services.v2.policy_copy_split.database_connectors.reads import (
    count_rows_naming_policy,
    read_mappings_naming_policy,
    read_policy_for_split,
    read_policy_ids_setting_parameters,
    read_saved_dynamic_with_name,
    read_saved_policies_naming_policy,
)
from policyengine_api.services.v2.policy_copy_split.database_connectors.updates import (
    repoint_legacy_policy_mapping,
    repoint_saved_policy,
)
from policyengine_api.services.v2.policy_copy_split.transformations import (
    split_stored_policy,
)
from policyengine_api.services.v2.policy_copy_split.types import (
    CopyReferences,
    ListedRows,
    MappingTarget,
    PolicyCopyOutcome,
    PolicyCopySplit,
    PreparedPolicyCopySplit,
    RepointedMapping,
    RepointedSavedPolicy,
    SavedDynamicIdentity,
    SavedPolicyTarget,
    SplitContent,
)
from policyengine_api.services.v2.policy_copy_split.validators import (
    PolicyCopySplitRefusedError,
    merge_dynamic_content,
    require_stored_row,
)
from policyengine_api.services.v2.user_dynamics.types import UserDynamicCreationInput

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from uuid import UUID

    from sqlmodel import Session

    from policyengine_api.data.v2.models import LegacyPolicyMapping
    from policyengine_api.services.v2.dynamics.types import (
        ResolvedDynamicCreationInput,
    )
    from policyengine_api.services.v2.policies.types import (
        ResolvedPolicyCreationInput,
    )
    from policyengine_api.services.v2.policy_copy_split.database_session import (
        PolicyCopySplitDatabaseSession,
    )
    from policyengine_api.services.v2.policy_copy_split.types import (
        StoredPolicySplit,
    )


def read_policy_copy_ids(session: Session) -> tuple[UUID, ...]:
    """Return every stored policy that sets a model assumption, oldest first."""
    return tuple(
        read_policy_ids_setting_parameters(session, DYNAMIC_PARAMETER_PREFIXES)
    )


def _mapping_dynamic(
    session: Session, mapping: LegacyPolicyMapping, split: StoredPolicySplit
) -> ResolvedDynamicCreationInput:
    """Return the dynamic the mapping will name: the copy's, or merged with its own.

    Raise PolicyCopySplitRefusedError when the mapping's dynamic can't take
    the copy's assumptions.
    """
    if mapping.dynamic_id is None:
        return split.dynamic
    existing = require_stored_row(
        read_dynamic_row(
            session, country_id=mapping.country_id, dynamic_id=mapping.dynamic_id
        ),
        f"dynamic {mapping.dynamic_id} of legacy policy {mapping.legacy_policy_id}",
    )
    model_version = require_stored_row(
        read_model_version(session, existing.tax_benefit_model_version_id),
        f"model version of dynamic {existing.id}",
    )
    return merge_dynamic_content(
        stored_policy_creation_input(
            existing, model_version, read_dynamic_parameter_values(session, existing.id)
        ),
        split.dynamic,
    )


def _prepare(
    session: Session, policy_id: UUID, *, lock: bool
) -> PreparedPolicyCopySplit | None:
    """Read what the split of one copy needs, locking the rows it changes with ``lock``.

    The locks are taken in the order API v1's copies take them, so the split
    waits for a copy instead of deadlocking with it: the copy of a v1 saved
    policy locks the legacy mapping, then saves a policy naming the mapped
    copy, whose foreign-key check locks the copy's row. So the mappings and
    saved policies naming the copy are locked before the copy, and read
    again once it is locked, since one committed meanwhile can name it and
    none can be added after. Return None when the policy is no longer stored
    or sets no model assumption.
    """
    if lock:
        read_mappings_naming_policy(session, policy_id, lock=True)
        read_saved_policies_naming_policy(session, policy_id, lock=True)
    policy = read_policy_for_split(session, policy_id, lock=lock)
    if policy is None:
        return None
    model_version = require_stored_row(
        read_model_version(session, policy.tax_benefit_model_version_id),
        f"model version of policy {policy.id}",
    )
    split = split_stored_policy(
        policy, model_version, read_parameter_values_with_names(session, [policy.id])
    )
    if split is None:
        return None
    simulations, reports, household_jobs = count_rows_naming_policy(session, policy.id)
    prepared = PreparedPolicyCopySplit(
        policy_id=policy.id,
        country_id=policy.country_id,
        policyengine_version=model_version.version,
        split=split,
        mapping_targets=(),
        saved_policy_targets=(),
        references=CopyReferences(
            simulations=simulations, reports=reports, household_jobs=household_jobs
        ),
        refusal_reason=None,
    )
    mappings = read_mappings_naming_policy(session, policy.id, lock=lock)
    try:
        mapping_targets = tuple(
            MappingTarget(
                mapping_id=mapping.id,
                country_id=mapping.country_id,
                legacy_policy_id=mapping.legacy_policy_id,
                previous_dynamic_id=mapping.dynamic_id,
                dynamic=_mapping_dynamic(session, mapping, split),
            )
            for mapping in mappings
        )
    except PolicyCopySplitRefusedError as refusal:
        return replace(prepared, refusal_reason=refusal.reason)
    dynamics_by_legacy_policy = {
        (target.country_id, target.legacy_policy_id): target.dynamic
        for target in mapping_targets
    }
    saved_policy_targets = tuple(
        SavedPolicyTarget(
            user_policy_id=saved_policy.id,
            user_id=saved_policy.user_id,
            country_id=saved_policy.country_id,
            name=saved_policy.name,
            dynamic=(
                split.dynamic
                if saved_policy.legacy_policy_id is None
                else dynamics_by_legacy_policy.get(
                    (saved_policy.country_id, saved_policy.legacy_policy_id),
                    split.dynamic,
                )
            ),
        )
        for saved_policy in read_saved_policies_naming_policy(
            session, policy.id, lock=lock
        )
    )
    return replace(
        prepared,
        mapping_targets=mapping_targets,
        saved_policy_targets=saved_policy_targets,
    )


def _content_hash(content: ResolvedPolicyCreationInput) -> str:
    return canonicalize_policy(content).content_hash


def _refused(prepared: PreparedPolicyCopySplit, *, applied: bool) -> PolicyCopySplit:
    return PolicyCopySplit(
        old_policy_id=prepared.policy_id,
        country_id=prepared.country_id,
        policyengine_version=prepared.policyengine_version,
        applied=applied,
        outcome=PolicyCopyOutcome.REFUSED,
        policy=None,
        dynamic=None,
        mappings=(),
        saved_policies=(),
        references=prepared.references,
        refusal_reason=prepared.refusal_reason,
    )


def _remaining_outcome(prepared: PreparedPolicyCopySplit) -> PolicyCopyOutcome:
    """Return deleted, unless a simulation, report or household job names the copy."""
    if prepared.references.total:
        return PolicyCopyOutcome.KEPT
    return PolicyCopyOutcome.DELETED


def plan_policy_copy_split(
    session: Session, policy_id: UUID, listed: ListedRows | None = None
) -> PolicyCopySplit | None:
    """Return what splitting one copy would change, reading only.

    Rows that don't exist yet have no ID. ``listed`` holds what the listing
    reported for earlier copies: applying commits each copy before the next,
    so a row an earlier copy creates is reused, and is reported so. Return
    None when the policy is no longer stored or sets no model assumption.
    """
    listed = ListedRows() if listed is None else listed
    prepared = _prepare(session, policy_id, lock=False)
    if prepared is None:
        return None
    if prepared.refusal_reason is not None:
        return _refused(prepared, applied=False)

    copy_policies: dict[str, SplitContent] = {}
    copy_dynamics: dict[str, SplitContent] = {}

    def listed_row(
        content: ResolvedPolicyCreationInput,
        *,
        copy_rows: dict[str, SplitContent],
        run_rows: dict[str, SplitContent],
        stored_id: Callable[[int, str], UUID | None],
    ) -> SplitContent:
        """Report one policy or dynamic as applying this copy would find or create it.

        Within one copy, applying reports a row the same way each time it
        meets it; a later copy finds the row an earlier copy created.
        """
        canonical = canonicalize_policy(content)
        if canonical.content_hash in copy_rows:
            return copy_rows[canonical.content_hash]
        earlier = run_rows.get(canonical.content_hash)
        if earlier is not None:
            row = SplitContent(
                id=earlier.id, content_hash=canonical.content_hash, created=False
            )
        else:
            row_id = stored_id(canonical.version, canonical.content_hash)
            row = SplitContent(
                id=row_id, content_hash=canonical.content_hash, created=row_id is None
            )
            run_rows[canonical.content_hash] = row
        copy_rows[canonical.content_hash] = row
        return row

    def stored_policy_id(
        canonicalization_version: int, content_hash: str
    ) -> UUID | None:
        stored = read_policy_by_content_identity(
            session,
            canonicalization_version=canonicalization_version,
            content_hash=content_hash,
        )
        return None if stored is None else stored.id

    def stored_dynamic_id(
        canonicalization_version: int, content_hash: str
    ) -> UUID | None:
        stored = read_dynamic_by_content_identity(
            session,
            canonicalization_version=canonicalization_version,
            content_hash=content_hash,
        )
        return None if stored is None else stored.id

    def listed_dynamic(content: ResolvedDynamicCreationInput) -> SplitContent:
        return listed_row(
            content,
            copy_rows=copy_dynamics,
            run_rows=listed.dynamics,
            stored_id=stored_dynamic_id,
        )

    policy = listed_row(
        prepared.split.policy,
        copy_rows=copy_policies,
        run_rows=listed.policies,
        stored_id=stored_policy_id,
    )
    plain_dynamic = listed_dynamic(prepared.split.dynamic)
    mappings = tuple(
        RepointedMapping(
            country_id=target.country_id,
            legacy_policy_id=target.legacy_policy_id,
            previous_dynamic_id=target.previous_dynamic_id,
            dynamic=listed_dynamic(target.dynamic),
        )
        for target in prepared.mapping_targets
    )
    saved_policies = []
    for target in prepared.saved_policy_targets:
        dynamic = listed_dynamic(target.dynamic)
        existing = (
            None
            if dynamic.id is None
            else read_saved_dynamic_with_name(
                session,
                user_id=target.user_id,
                country_id=target.country_id,
                dynamic_id=dynamic.id,
                name=target.name,
            )
        )
        identity = SavedDynamicIdentity(
            user_id=target.user_id,
            country_id=target.country_id,
            dynamic_content_hash=dynamic.content_hash,
            name=target.name,
        )
        saved_policies.append(
            RepointedSavedPolicy(
                user_policy_id=target.user_policy_id,
                dynamic=dynamic,
                saved_dynamic_id=None if existing is None else existing.id,
                saved_dynamic_created=existing is None
                and identity not in listed.saved_dynamics,
            )
        )
        listed.saved_dynamics.add(identity)
    return PolicyCopySplit(
        old_policy_id=prepared.policy_id,
        country_id=prepared.country_id,
        policyengine_version=prepared.policyengine_version,
        applied=False,
        outcome=_remaining_outcome(prepared),
        policy=policy,
        dynamic=plain_dynamic,
        mappings=mappings,
        saved_policies=tuple(saved_policies),
        references=prepared.references,
        refusal_reason=None,
    )


def split_policy_copy_in_session(
    session: Session, policy_id: UUID
) -> PolicyCopySplit | None:
    """Split one copy in the caller's transaction, which commits it.

    The copy is locked first, so nothing can start naming it before the
    transaction ends. Return None when the policy is no longer stored or sets
    no model assumption. Raise PolicyCopyIntegrityError, and the policy and
    dynamic creation errors, for stored rows that contradict their keys.
    """
    from policyengine_api.services.v2.dynamics.services import (
        create_resolved_dynamic,
    )
    from policyengine_api.services.v2.policies.services import (
        create_resolved_policy,
    )
    from policyengine_api.services.v2.user_dynamics.services import (
        create_user_dynamic_in_session,
    )

    prepared = _prepare(session, policy_id, lock=True)
    if prepared is None:
        return None
    if prepared.refusal_reason is not None:
        return _refused(prepared, applied=True)

    stored_dynamics: dict[str, SplitContent] = {}

    def stored_dynamic(content: ResolvedDynamicCreationInput) -> SplitContent:
        content_hash = _content_hash(content)
        if content_hash not in stored_dynamics:
            result = create_resolved_dynamic(session, content)
            stored_dynamics[content_hash] = SplitContent(
                id=result.dynamic_id, content_hash=content_hash, created=result.created
            )
        return stored_dynamics[content_hash]

    policy_result = create_resolved_policy(session, prepared.split.policy)
    plain_dynamic = stored_dynamic(prepared.split.dynamic)
    mappings = []
    for mapping_target in prepared.mapping_targets:
        dynamic = stored_dynamic(mapping_target.dynamic)
        repoint_legacy_policy_mapping(
            session,
            mapping_target.mapping_id,
            policy_id=policy_result.policy_id,
            dynamic_id=require_stored_row(dynamic.id, "a stored dynamic's ID"),
        )
        mappings.append(
            RepointedMapping(
                country_id=mapping_target.country_id,
                legacy_policy_id=mapping_target.legacy_policy_id,
                previous_dynamic_id=mapping_target.previous_dynamic_id,
                dynamic=dynamic,
            )
        )
    saved_policies = []
    for saved_policy_target in prepared.saved_policy_targets:
        dynamic = stored_dynamic(saved_policy_target.dynamic)
        dynamic_id = require_stored_row(dynamic.id, "a stored dynamic's ID")
        repoint_saved_policy(
            session,
            saved_policy_target.user_policy_id,
            policy_id=policy_result.policy_id,
        )
        existing = read_saved_dynamic_with_name(
            session,
            user_id=saved_policy_target.user_id,
            country_id=saved_policy_target.country_id,
            dynamic_id=dynamic_id,
            name=saved_policy_target.name,
        )
        saved_dynamic_id = (
            existing.id
            if existing is not None
            else create_user_dynamic_in_session(
                session,
                UserDynamicCreationInput.model_validate(
                    {
                        "country_id": saved_policy_target.country_id,
                        "user_id": saved_policy_target.user_id,
                        "dynamic_id": dynamic_id,
                        "name": saved_policy_target.name,
                        "description": None,
                    }
                ),
            ).id
        )
        saved_policies.append(
            RepointedSavedPolicy(
                user_policy_id=saved_policy_target.user_policy_id,
                dynamic=dynamic,
                saved_dynamic_id=saved_dynamic_id,
                saved_dynamic_created=existing is None,
            )
        )
    outcome = _remaining_outcome(prepared)
    if outcome is PolicyCopyOutcome.DELETED:
        delete_policy(session, prepared.policy_id)
    return PolicyCopySplit(
        old_policy_id=prepared.policy_id,
        country_id=prepared.country_id,
        policyengine_version=prepared.policyengine_version,
        applied=True,
        outcome=outcome,
        policy=SplitContent(
            id=policy_result.policy_id,
            content_hash=_content_hash(prepared.split.policy),
            created=policy_result.created,
        ),
        dynamic=plain_dynamic,
        mappings=tuple(mappings),
        saved_policies=tuple(saved_policies),
        references=prepared.references,
        refusal_reason=None,
    )


class V2PolicyCopySplitService:
    """List or apply the split of every stored copy, one transaction per copy."""

    def __init__(self, database_session: PolicyCopySplitDatabaseSession) -> None:
        """Open sessions through ``database_session``."""
        self._database_session = database_session

    def list_policy_copy_splits(self) -> tuple[PolicyCopySplit, ...]:
        """Return what splitting every copy would change, in one read session."""
        listed = ListedRows()
        with self._database_session.read() as session:
            planned = (
                plan_policy_copy_split(session, policy_id, listed)
                for policy_id in read_policy_copy_ids(session)
            )
            return tuple(split for split in planned if split is not None)

    def split_policy_copies(self) -> Iterator[PolicyCopySplit]:
        """Split each copy in its own transaction, yielding each as it commits."""
        with self._database_session.read() as session:
            policy_ids = read_policy_copy_ids(session)
        for policy_id in policy_ids:
            with self._database_session.transaction() as session:
                split = split_policy_copy_in_session(session, policy_id)
            if split is not None:
                yield split

    def count_policy_copies(self) -> int:
        """Return how many stored policies still set a model assumption."""
        with self._database_session.read() as session:
            return len(read_policy_copy_ids(session))
