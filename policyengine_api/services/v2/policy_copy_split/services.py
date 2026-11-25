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

import time
from dataclasses import replace
from typing import TYPE_CHECKING, Protocol

from sqlalchemy.exc import OperationalError

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
    is_lock_conflict,
    merge_dynamic_content,
    require_stored_row,
)
from policyengine_api.services.v2.user_dynamics.types import UserDynamicCreationInput

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from uuid import UUID

    from sqlmodel import Session

    from policyengine_api.data.v2.models import Dynamic, LegacyPolicyMapping, Policy
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
    prepared = PreparedPolicyCopySplit(
        policy_id=policy.id,
        country_id=policy.country_id,
        policyengine_version=model_version.version,
        split=split,
        mapping_targets=(),
        saved_policy_targets=(),
        references=count_rows_naming_policy(session, policy.id),
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


class _SplitRows(Protocol):
    """Where one copy's split finds or puts its rows: in a listing, or for real."""

    def policy(self, content: ResolvedPolicyCreationInput) -> SplitContent:
        """Find, or create or report as new, the policy with this content."""
        ...

    def dynamic(self, content: ResolvedDynamicCreationInput) -> SplitContent:
        """Find, or create or report as new, the dynamic with this content."""
        ...

    def repoint_mapping(
        self, target: MappingTarget, *, policy: SplitContent, dynamic: SplitContent
    ) -> None:
        """Point the mapping at the policy and dynamic."""
        ...

    def repoint_saved_policy(
        self, target: SavedPolicyTarget, *, policy: SplitContent
    ) -> None:
        """Point the saved policy at the policy."""
        ...

    def saved_dynamic(
        self, target: SavedPolicyTarget, *, dynamic: SplitContent
    ) -> tuple[UUID | None, bool]:
        """Give the saved policy's owner a saved dynamic naming the dynamic.

        Return the saved dynamic's ID (None when a listing would create it)
        and whether it is new.
        """
        ...

    def delete_copy(self, policy_id: UUID) -> None:
        """Delete the copy, which nothing names any more."""
        ...


def _split_prepared(
    prepared: PreparedPolicyCopySplit, rows: _SplitRows, *, applied: bool
) -> PolicyCopySplit:
    """Carry out one copy's split through ``rows``, and say what it did.

    A listing and a run both go through here, so they report the same steps.
    """
    policy = rows.policy(prepared.split.policy)
    plain_dynamic = rows.dynamic(prepared.split.dynamic)
    mappings = []
    for mapping_target in prepared.mapping_targets:
        dynamic = rows.dynamic(mapping_target.dynamic)
        rows.repoint_mapping(mapping_target, policy=policy, dynamic=dynamic)
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
        dynamic = rows.dynamic(saved_policy_target.dynamic)
        rows.repoint_saved_policy(saved_policy_target, policy=policy)
        saved_dynamic_id, saved_dynamic_created = rows.saved_dynamic(
            saved_policy_target, dynamic=dynamic
        )
        saved_policies.append(
            RepointedSavedPolicy(
                user_policy_id=saved_policy_target.user_policy_id,
                dynamic=dynamic,
                saved_dynamic_id=saved_dynamic_id,
                saved_dynamic_created=saved_dynamic_created,
            )
        )
    outcome = _remaining_outcome(prepared)
    if outcome is PolicyCopyOutcome.DELETED:
        rows.delete_copy(prepared.policy_id)
    return PolicyCopySplit(
        old_policy_id=prepared.policy_id,
        country_id=prepared.country_id,
        policyengine_version=prepared.policyengine_version,
        applied=applied,
        outcome=outcome,
        policy=policy,
        dynamic=plain_dynamic,
        mappings=tuple(mappings),
        saved_policies=tuple(saved_policies),
        references=prepared.references,
        refusal_reason=None,
    )


class _StoredRowReader(Protocol):
    def __call__(
        self, session: Session, *, canonicalization_version: int, content_hash: str
    ) -> Policy | Dynamic | None: ...


class _ListedSplitRows:
    """Report the rows one copy's split would find or create, changing nothing.

    ``listed`` carries what earlier copies in the listing reported: a run
    commits each copy before the next, so a later copy finds a row an
    earlier one created, and is reported so. Within one copy, a row is
    reported the same way each time, as a run reports it.
    """

    def __init__(self, session: Session, listed: ListedRows) -> None:
        """Read through ``session``, adding to ``listed``."""
        self._session = session
        self._listed = listed
        self._copy_policies: dict[str, SplitContent] = {}
        self._copy_dynamics: dict[str, SplitContent] = {}

    def _row(
        self,
        content: ResolvedPolicyCreationInput,
        *,
        copy_rows: dict[str, SplitContent],
        run_rows: dict[str, SplitContent],
        read_stored: _StoredRowReader,
    ) -> SplitContent:
        canonical = canonicalize_policy(content)
        if canonical.content_hash in copy_rows:
            return copy_rows[canonical.content_hash]
        earlier = run_rows.get(canonical.content_hash)
        if earlier is not None:
            row = SplitContent(
                id=earlier.id, content_hash=canonical.content_hash, created=False
            )
        else:
            stored = read_stored(
                self._session,
                canonicalization_version=canonical.version,
                content_hash=canonical.content_hash,
            )
            row = SplitContent(
                id=None if stored is None else stored.id,
                content_hash=canonical.content_hash,
                created=stored is None,
            )
            run_rows[canonical.content_hash] = row
        copy_rows[canonical.content_hash] = row
        return row

    def policy(self, content: ResolvedPolicyCreationInput) -> SplitContent:
        """Report the policy as stored, or as one this run would create."""
        return self._row(
            content,
            copy_rows=self._copy_policies,
            run_rows=self._listed.policies,
            read_stored=read_policy_by_content_identity,
        )

    def dynamic(self, content: ResolvedDynamicCreationInput) -> SplitContent:
        """Report the dynamic as stored, or as one this run would create."""
        return self._row(
            content,
            copy_rows=self._copy_dynamics,
            run_rows=self._listed.dynamics,
            read_stored=read_dynamic_by_content_identity,
        )

    def repoint_mapping(
        self, target: MappingTarget, *, policy: SplitContent, dynamic: SplitContent
    ) -> None:
        """Change nothing: a listing only reports the mapping."""

    def repoint_saved_policy(
        self, target: SavedPolicyTarget, *, policy: SplitContent
    ) -> None:
        """Change nothing: a listing only reports the saved policy."""

    def saved_dynamic(
        self, target: SavedPolicyTarget, *, dynamic: SplitContent
    ) -> tuple[UUID | None, bool]:
        """Report the owner's identical saved dynamic, or one this run would add."""
        existing = (
            None
            if dynamic.id is None
            else read_saved_dynamic_with_name(
                self._session,
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
        created = existing is None and identity not in self._listed.saved_dynamics
        self._listed.saved_dynamics.add(identity)
        return (None if existing is None else existing.id), created

    def delete_copy(self, policy_id: UUID) -> None:
        """Change nothing: a listing only reports the deletion."""


def _stored_id(content: SplitContent) -> UUID:
    """Return the ID of a row the run found or created; it always has one."""
    return require_stored_row(
        content.id, f"the row with content {content.content_hash}"
    )


class _StoredSplitRows:
    """Find or create one copy's rows, and change what names the copy."""

    def __init__(self, session: Session) -> None:
        """Write through ``session``, in the caller's transaction."""
        self._session = session
        self._policies: dict[str, SplitContent] = {}
        self._dynamics: dict[str, SplitContent] = {}

    def policy(self, content: ResolvedPolicyCreationInput) -> SplitContent:
        """Find or create the policy (C1 · 36's ``create_resolved_policy``)."""
        from policyengine_api.services.v2.policies.services import (
            create_resolved_policy,
        )

        content_hash = _content_hash(content)
        if content_hash not in self._policies:
            result = create_resolved_policy(self._session, content)
            self._policies[content_hash] = SplitContent(
                id=result.policy_id, content_hash=content_hash, created=result.created
            )
        return self._policies[content_hash]

    def dynamic(self, content: ResolvedDynamicCreationInput) -> SplitContent:
        """Find or create the dynamic (C1 · 36's ``create_resolved_dynamic``)."""
        from policyengine_api.services.v2.dynamics.services import (
            create_resolved_dynamic,
        )

        content_hash = _content_hash(content)
        if content_hash not in self._dynamics:
            result = create_resolved_dynamic(self._session, content)
            self._dynamics[content_hash] = SplitContent(
                id=result.dynamic_id, content_hash=content_hash, created=result.created
            )
        return self._dynamics[content_hash]

    def repoint_mapping(
        self, target: MappingTarget, *, policy: SplitContent, dynamic: SplitContent
    ) -> None:
        """Point the mapping at the policy and dynamic."""
        repoint_legacy_policy_mapping(
            self._session,
            target.mapping_id,
            policy_id=_stored_id(policy),
            dynamic_id=_stored_id(dynamic),
        )

    def repoint_saved_policy(
        self, target: SavedPolicyTarget, *, policy: SplitContent
    ) -> None:
        """Point the saved policy at the policy; its name and description stay."""
        repoint_saved_policy(
            self._session, target.user_policy_id, policy_id=_stored_id(policy)
        )

    def saved_dynamic(
        self, target: SavedPolicyTarget, *, dynamic: SplitContent
    ) -> tuple[UUID | None, bool]:
        """Give the saved policy's owner a saved dynamic naming the dynamic.

        It takes the saved policy's name and no description (C1 · 43's
        ``create_user_dynamic_in_session``); an identical one the owner
        already has is reused.
        """
        from policyengine_api.services.v2.user_dynamics.services import (
            create_user_dynamic_in_session,
        )

        dynamic_id = _stored_id(dynamic)
        existing = read_saved_dynamic_with_name(
            self._session,
            user_id=target.user_id,
            country_id=target.country_id,
            dynamic_id=dynamic_id,
            name=target.name,
        )
        if existing is not None:
            return existing.id, False
        saved_dynamic = create_user_dynamic_in_session(
            self._session,
            UserDynamicCreationInput.model_validate(
                {
                    "country_id": target.country_id,
                    "user_id": target.user_id,
                    "dynamic_id": dynamic_id,
                    "name": target.name,
                    "description": None,
                }
            ),
        )
        return saved_dynamic.id, True

    def delete_copy(self, policy_id: UUID) -> None:
        """Delete the copy; its values go with it."""
        delete_policy(self._session, policy_id)


def plan_policy_copy_split(
    session: Session, policy_id: UUID, listed: ListedRows | None = None
) -> PolicyCopySplit | None:
    """Return what splitting one copy would change, reading only.

    Rows that don't exist yet have no ID. ``listed`` holds what the listing
    reported for earlier copies. Return None when the policy is no longer
    stored or sets no model assumption.
    """
    prepared = _prepare(session, policy_id, lock=False)
    if prepared is None:
        return None
    if prepared.refusal_reason is not None:
        return _refused(prepared, applied=False)
    return _split_prepared(
        prepared,
        _ListedSplitRows(session, ListedRows() if listed is None else listed),
        applied=False,
    )


def split_policy_copy_in_session(
    session: Session, policy_id: UUID
) -> PolicyCopySplit | None:
    """Split one copy in the caller's transaction, which commits it.

    The rows it changes are locked first, so nothing can start naming the
    copy before the transaction ends. Return None when the policy is no
    longer stored or sets no model assumption. Raise PolicyCopyIntegrityError,
    and the policy and dynamic creation errors, for stored rows that
    contradict their keys.
    """
    prepared = _prepare(session, policy_id, lock=True)
    if prepared is None:
        return None
    if prepared.refusal_reason is not None:
        return _refused(prepared, applied=True)
    return _split_prepared(prepared, _StoredSplitRows(session), applied=True)


class V2PolicyCopySplitService:
    """List or apply the split of every stored copy, one transaction per copy.

    A copy whose transaction meets a lock conflict (the lock timeout ran out,
    or PostgreSQL found a deadlock) is rolled back and tried again, up to
    ``attempts`` times, ``retry_delay_seconds`` apart. With the command's
    lock timeout shorter than PostgreSQL's deadlock_timeout, the split gives
    way to API v1's live writes in a lock cycle.
    """

    def __init__(
        self,
        database_session: PolicyCopySplitDatabaseSession,
        *,
        attempts: int = 5,
        retry_delay_seconds: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Open sessions through ``database_session``."""
        self._database_session = database_session
        self._attempts = attempts
        self._retry_delay_seconds = retry_delay_seconds
        self._sleep = sleep

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
            split = self._split_with_retries(policy_id)
            if split is not None:
                yield split

    def _split_with_retries(self, policy_id: UUID) -> PolicyCopySplit | None:
        """Split one copy, trying it again after a lock conflict.

        Raise the last lock conflict when every attempt meets one, and any
        other database error at once.
        """
        attempt = 1
        while True:
            try:
                with self._database_session.transaction() as session:
                    return split_policy_copy_in_session(session, policy_id)
            except OperationalError as error:
                if attempt >= self._attempts or not is_lock_conflict(error):
                    raise
            attempt += 1
            self._sleep(self._retry_delay_seconds)

    def count_policy_copies(self) -> int:
        """Return how many stored policies still set a model assumption."""
        with self._database_session.read() as session:
            return len(read_policy_copy_ids(session))
