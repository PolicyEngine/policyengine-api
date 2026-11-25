#!/usr/bin/env python3
"""Split each stored v2 policy that sets a model assumption into a policy and dynamic.

Usage::

    split_v2_policy_copies.py            # list what would change; change nothing
    split_v2_policy_copies.py --apply    # make the changes

Without ``--apply`` it reads in one READ ONLY transaction and lists, for each
stored policy that sets a model assumption (``gov.simulation.``, US
``simulation.``, UK ``gov.dynamic.``), the policy and dynamic it would split
into, the legacy mappings and saved policies it would re-point, the saved
dynamics it would add, and whether the old copy would be deleted, kept or
refused. With ``--apply`` it makes those changes, one transaction per copy,
and reports the IDs of every row it points at or creates.
``policyengine_api.services.v2.policy_copy_split.services`` describes the
split.

It exits with 0 when, afterwards, no stored policy sets a model assumption
(for the listing: when every copy would be deleted), and with 1 otherwise,
such as when a copy is kept because a simulation, report or household
calculation names it, or refused. Any other failure, such as missing
settings, an unreachable database (after 10 seconds) or a lock wait of more
than 10 seconds, raises, so Python prints its traceback and also exits with
1; the copies already reported have committed, and running it again
carries on.

It connects as the temporary role ``policyengine_v2_policy_copy_split``,
which the operator creates with the grants in
``docs/migration/stage-10-v2-policies.md`` and drops afterwards:
``V2_POLICY_COPY_SPLIT_DATABASE_URL`` names it, and ``V2_SUPABASE_PROJECT_REF``
and ``V2_SUPABASE_ENVIRONMENT`` the Supabase project the URL must name.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from typing import TYPE_CHECKING, Protocol

from policyengine_api.data.v2.settings import (
    load_v2_policy_copy_split_database_settings,
)
from policyengine_api.services.v2.policy_copy_split.types import (
    PolicyCopyOutcome,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Sequence
    from contextlib import AbstractContextManager

    from sqlalchemy.engine import URL

    from policyengine_api.services.v2.policy_copy_split.types import (
        CopyReferences,
        PolicyCopySplit,
        RepointedSavedPolicy,
        SplitContent,
    )


CONNECT_TIMEOUT_SECONDS = 10
LOCK_TIMEOUT_MILLISECONDS = 10_000
STATEMENT_TIMEOUT_MILLISECONDS = 60_000


class PolicyCopySplitter(Protocol):
    """The split service operations this command calls."""

    def list_policy_copy_splits(self) -> tuple[PolicyCopySplit, ...]:
        """Return what splitting every copy would change."""
        ...

    def split_policy_copies(self) -> Iterator[PolicyCopySplit]:
        """Split each copy in its own transaction, yielding each as it commits."""
        ...

    def count_policy_copies(self) -> int:
        """Return how many stored policies still set a model assumption."""
        ...


@contextmanager
def splitter_on_temporary_role(*, writable: bool) -> Iterator[PolicyCopySplitter]:
    """Yield the split service on the temporary role's database connection.

    Without ``writable``, every transaction is READ ONLY, so the database
    refuses any write. Raise V2ConfigurationError for missing or invalid
    settings.
    """
    settings = load_v2_policy_copy_split_database_settings()
    url = with_time_limits(settings.connection.url)
    # These modules are imported only when the command runs, as they need the
    # connection.
    from policyengine_api.data.v2.database import (
        unpooled_v2_read_only_sessions,
        unpooled_v2_sessions,
    )
    from policyengine_api.services.v2.policy_copy_split.database_session import (
        PolicyCopySplitDatabaseSession,
    )
    from policyengine_api.services.v2.policy_copy_split.services import (
        V2PolicyCopySplitService,
    )

    open_sessions = unpooled_v2_sessions if writable else unpooled_v2_read_only_sessions
    with open_sessions(url) as session_factory:
        yield V2PolicyCopySplitService(PolicyCopySplitDatabaseSession(session_factory))


def with_time_limits(url: URL) -> URL:
    """Return the URL with a connection timeout, and lock and statement timeouts.

    A lock wait then fails after a while instead of lasting indefinitely
    while the split holds a copy's row lock, which blocks a live write that
    names the copy. Earlier copies' transactions have committed by then, and
    running the command again carries on.
    """
    time_limits = (
        f"-c lock_timeout={LOCK_TIMEOUT_MILLISECONDS} "
        f"-c statement_timeout={STATEMENT_TIMEOUT_MILLISECONDS}"
    )
    existing_options = url.query.get("options")
    return url.update_query_dict(
        {
            "connect_timeout": str(CONNECT_TIMEOUT_SECONDS),
            "options": (
                time_limits
                if existing_options is None
                else f"{existing_options} {time_limits}"
            ),
        }
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Split every stored v2 policy that sets a model assumption into a "
            "policy and a dynamic. Without --apply, only list what would change."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="make the changes; without it, nothing is changed",
    )
    return parser


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else plural or singular + 's'}"


def _content(kind: str, content: SplitContent) -> str:
    """Name a policy or dynamic: its ID, or its content hash if it is still to come."""
    if content.id is None and content.created:
        return f"{kind}: would be created (content hash {content.content_hash[:12]})"
    if content.id is None:
        return (
            f"{kind}: the one listed above would be reused "
            f"(content hash {content.content_hash[:12]})"
        )
    return f"{kind} {content.id} ({'created' if content.created else 'already stored'})"


def _dynamic_name(content: SplitContent) -> str:
    if content.id is None:
        return f"a new dynamic (content hash {content.content_hash[:12]})"
    return f"dynamic {content.id}"


def _references(references: CopyReferences) -> str:
    return (
        f"named by {_plural(references.simulations, 'simulation')}, "
        f"{_plural(references.reports, 'report')} and "
        f"{_plural(references.household_jobs, 'household calculation')}"
    )


def _outcome(split: PolicyCopySplit) -> str:
    if split.outcome is PolicyCopyOutcome.REFUSED:
        refused = "refused" if split.applied else "would be refused"
        reason = split.refusal_reason.value if split.refusal_reason else "unknown"
        return f"{refused} ({reason}); nothing changes for it"
    if split.outcome is PolicyCopyOutcome.KEPT:
        kept = "kept" if split.applied else "would be kept"
        return f"{kept}: {_references(split.references)}"
    return "deleted" if split.applied else "would be deleted"


def _describe(split: PolicyCopySplit) -> list[str]:
    """Return the report on one copy: one heading, then one entry per change."""
    report = [
        f"Policy copy {split.old_policy_id} ({split.country_id}, catalog version "
        f"{split.policyengine_version}): {_outcome(split)}"
    ]
    if split.policy is None or split.dynamic is None:
        return report
    policy_name = (
        "the new policy" if split.policy.id is None else f"policy {split.policy.id}"
    )
    report += [
        "  " + _content("policy", split.policy),
        "  " + _content("dynamic", split.dynamic),
    ]
    now = "now" if split.applied else "would point at"
    for mapping in split.mappings:
        report.append(
            f"  legacy policy {mapping.country_id} {mapping.legacy_policy_id}: "
            f"{now} {policy_name} and {_dynamic_name(mapping.dynamic)} "
            f"(was dynamic {mapping.previous_dynamic_id or 'none'})"
        )
    for saved_policy in split.saved_policies:
        report.append(
            f"  saved policy {saved_policy.user_policy_id}: {now} {policy_name}; "
            f"{_saved_dynamic(saved_policy)} for {_dynamic_name(saved_policy.dynamic)}"
        )
    return report


def _saved_dynamic(saved_policy: RepointedSavedPolicy) -> str:
    """Name the saved dynamic a saved policy's owner gets, or would get."""
    if saved_policy.saved_dynamic_id is None:
        if saved_policy.saved_dynamic_created:
            return "saved dynamic: would be created"
        return "saved dynamic: an identical one listed above would be reused"
    if saved_policy.saved_dynamic_created:
        return f"saved dynamic {saved_policy.saved_dynamic_id} (created)"
    return f"saved dynamic {saved_policy.saved_dynamic_id} (already saved)"


def _counts(splits: Iterable[PolicyCopySplit]) -> dict[PolicyCopyOutcome, int]:
    counts = dict.fromkeys(PolicyCopyOutcome, 0)
    for split in splits:
        counts[split.outcome] += 1
    return counts


def _list(splitter: PolicyCopySplitter) -> int:
    print("Read-only listing: nothing was changed. Run with --apply to change it.")
    splits = splitter.list_policy_copy_splits()
    for split in splits:
        print("\n".join(_describe(split)))
    if not splits:
        print("No stored policy sets a model assumption.")
        return 0
    counts = _counts(splits)
    print(
        f"{_plural(len(splits), 'policy copy', 'policy copies')} "
        f"{'sets' if len(splits) == 1 else 'set'} a model assumption: "
        f"{counts[PolicyCopyOutcome.DELETED]} would be deleted, "
        f"{counts[PolicyCopyOutcome.KEPT]} would be kept and "
        f"{counts[PolicyCopyOutcome.REFUSED]} would be refused."
    )
    return 0 if len(splits) == counts[PolicyCopyOutcome.DELETED] else 1


def _apply(splitter: PolicyCopySplitter) -> int:
    print("Applying: each policy copy is changed in its own transaction.")
    splits = []
    for split in splitter.split_policy_copies():
        splits.append(split)
        print("\n".join(_describe(split)), flush=True)
    remaining = splitter.count_policy_copies()
    counts = _counts(splits)
    print(
        f"{_plural(len(splits), 'policy copy', 'policy copies')}: "
        f"{counts[PolicyCopyOutcome.DELETED]} deleted, "
        f"{counts[PolicyCopyOutcome.KEPT]} kept and "
        f"{counts[PolicyCopyOutcome.REFUSED]} refused. "
        f"{_plural(remaining, 'stored policy', 'stored policies')} still "
        f"{'sets' if remaining == 1 else 'set'} a model assumption."
    )
    return 0 if remaining == 0 else 1


def main(
    argv: Sequence[str] | None = None,
    *,
    splitter_factory: Callable[..., AbstractContextManager[PolicyCopySplitter]] = (
        splitter_on_temporary_role
    ),
) -> int:
    """List or apply the split; return 0 when no copy is left, and 1 otherwise."""
    arguments = _parser().parse_args(argv)
    with splitter_factory(writable=arguments.apply) as splitter:
        return _apply(splitter) if arguments.apply else _list(splitter)


if __name__ == "__main__":
    raise SystemExit(main())
