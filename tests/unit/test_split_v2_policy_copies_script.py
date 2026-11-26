"""Tests for the command that splits stored policy copies holding model assumptions.

The command only reads unless given ``--apply``. Each copy's report names the
old copy, its policy and dynamic, every legacy mapping and saved policy it
re-points and every saved dynamic it adds, so C1 · 49's operator can compare
the run with a backup.
"""

from __future__ import annotations

import subprocess
import sys
from contextlib import contextmanager
from typing import TYPE_CHECKING
from uuid import UUID

import pytest
from sqlalchemy.orm import sessionmaker

from policyengine_api.constants import REPO
from policyengine_api.data.v2.settings import (
    V2_POLICY_COPY_SPLIT_DATABASE_URL,
    V2_SUPABASE_ENVIRONMENT,
    V2_SUPABASE_PROJECT_REF,
    V2ConfigurationError,
)
from policyengine_api.services.v2.policy_copy_split.types import (
    CopyReferences,
    PolicyCopyOutcome,
    PolicyCopyRefusalReason,
    PolicyCopySplit,
    RepointedMapping,
    RepointedSavedPolicy,
    SplitContent,
)
from scripts import split_v2_policy_copies

if TYPE_CHECKING:
    from collections.abc import Iterator

OLD_COPY_ID = UUID("00000000-0000-0000-0000-0000000c0001")
SPLIT_POLICY_ID = UUID("00000000-0000-0000-0000-0000000c0002")
SPLIT_DYNAMIC_ID = UUID("00000000-0000-0000-0000-0000000c0003")
EARLIER_DYNAMIC_ID = UUID("00000000-0000-0000-0000-0000000c0004")
MERGED_DYNAMIC_ID = UUID("00000000-0000-0000-0000-0000000c0005")
SAVED_POLICY_ID = UUID("00000000-0000-0000-0000-0000000c0006")
SAVED_DYNAMIC_ID = UUID("00000000-0000-0000-0000-0000000c0007")
POLICY_HASH = "1" * 64
DYNAMIC_HASH = "2" * 64
MERGED_HASH = "3" * 64
NO_REFERENCES = CopyReferences(simulations=0, reports=0, household_jobs=0)


def _split(
    *,
    applied: bool,
    outcome: PolicyCopyOutcome = PolicyCopyOutcome.DELETED,
    references: CopyReferences = NO_REFERENCES,
    refusal_reason: PolicyCopyRefusalReason | None = None,
) -> PolicyCopySplit:
    """One UK copy: a mapping that already named a dynamic, and one saved policy."""
    if refusal_reason is not None:
        return PolicyCopySplit(
            old_policy_id=OLD_COPY_ID,
            country_id="uk",
            policyengine_version="2.174.1",
            applied=applied,
            outcome=PolicyCopyOutcome.REFUSED,
            policy=None,
            dynamic=None,
            mappings=(),
            saved_policies=(),
            references=references,
            refusal_reason=refusal_reason,
        )
    merged = SplitContent(
        id=MERGED_DYNAMIC_ID if applied else None,
        content_hash=MERGED_HASH,
        created=True,
    )
    return PolicyCopySplit(
        old_policy_id=OLD_COPY_ID,
        country_id="uk",
        policyengine_version="2.174.1",
        applied=applied,
        outcome=outcome,
        policy=SplitContent(
            id=SPLIT_POLICY_ID, content_hash=POLICY_HASH, created=False
        ),
        dynamic=SplitContent(
            id=SPLIT_DYNAMIC_ID if applied else None,
            content_hash=DYNAMIC_HASH,
            created=True,
        ),
        mappings=(
            RepointedMapping(
                country_id="uk",
                legacy_policy_id=1234,
                previous_dynamic_id=EARLIER_DYNAMIC_ID,
                dynamic=merged,
            ),
        ),
        saved_policies=(
            RepointedSavedPolicy(
                user_policy_id=SAVED_POLICY_ID,
                dynamic=merged,
                saved_dynamic_id=SAVED_DYNAMIC_ID if applied else None,
                saved_dynamic_created=True,
            ),
        ),
        references=references,
        refusal_reason=None,
    )


class FakeSplitter:
    """Return the given splits and remaining count, recording each call."""

    def __init__(
        self, splits: tuple[PolicyCopySplit, ...], *, remaining_copies: int = 0
    ) -> None:
        self.splits = splits
        self.remaining_copies = remaining_copies
        self.calls: list[str] = []

    def list_policy_copy_splits(self) -> tuple[PolicyCopySplit, ...]:
        self.calls.append("list")
        return self.splits

    def split_policy_copies(self) -> Iterator[PolicyCopySplit]:
        self.calls.append("split")
        yield from self.splits

    def count_policy_copies(self) -> int:
        self.calls.append("count")
        return self.remaining_copies


class RecordingFactory:
    """Build the fake splitter, recording whether the command asked to write."""

    def __init__(self, splitter: FakeSplitter) -> None:
        self.splitter = splitter
        self.writable: list[bool] = []

    @contextmanager
    def __call__(self, *, writable: bool) -> Iterator[FakeSplitter]:
        self.writable.append(writable)
        yield self.splitter


def test_the_command_only_lists_without_apply(capsys) -> None:
    factory = RecordingFactory(FakeSplitter((_split(applied=False),)))

    exit_status = split_v2_policy_copies.main([], splitter_factory=factory)

    output = capsys.readouterr().out
    assert exit_status == 0
    assert factory.writable == [False]
    assert factory.splitter.calls == ["list"]
    assert "Read-only listing: nothing was changed." in output
    assert f"Policy copy {OLD_COPY_ID} (uk, catalog version 2.174.1)" in output
    assert "would be deleted" in output
    assert f"policy {SPLIT_POLICY_ID} (already stored)" in output
    assert f"dynamic: would be created (content hash {DYNAMIC_HASH[:12]})" in output
    assert "legacy policy uk 1234" in output
    assert f"was dynamic {EARLIER_DYNAMIC_ID}" in output
    assert f"saved policy {SAVED_POLICY_ID}" in output
    assert "1 policy copy sets a model assumption: 1 would be deleted" in output


def test_the_command_applies_and_names_every_row_it_changes(capsys) -> None:
    factory = RecordingFactory(FakeSplitter((_split(applied=True),)))

    exit_status = split_v2_policy_copies.main(["--apply"], splitter_factory=factory)

    output = capsys.readouterr().out
    assert exit_status == 0
    assert factory.writable == [True]
    assert factory.splitter.calls == ["split", "count"]
    assert f"Policy copy {OLD_COPY_ID} (uk, catalog version 2.174.1): deleted" in (
        output
    )
    assert f"policy {SPLIT_POLICY_ID} (already stored)" in output
    assert f"dynamic {SPLIT_DYNAMIC_ID} (created)" in output
    assert (
        f"legacy policy uk 1234: now policy {SPLIT_POLICY_ID} and dynamic "
        f"{MERGED_DYNAMIC_ID} (was dynamic {EARLIER_DYNAMIC_ID})"
    ) in output
    assert (
        f"saved policy {SAVED_POLICY_ID}: now policy {SPLIT_POLICY_ID}; "
        f"saved dynamic {SAVED_DYNAMIC_ID} (created) for dynamic {MERGED_DYNAMIC_ID}"
    ) in output
    assert "0 stored policies still set a model assumption." in output


def test_a_kept_copy_is_reported_and_fails_the_run(capsys) -> None:
    references = CopyReferences(simulations=1, reports=2, household_jobs=0)
    factory = RecordingFactory(
        FakeSplitter(
            (
                _split(
                    applied=True,
                    outcome=PolicyCopyOutcome.KEPT,
                    references=references,
                ),
            ),
            remaining_copies=1,
        )
    )

    exit_status = split_v2_policy_copies.main(["--apply"], splitter_factory=factory)

    output = capsys.readouterr().out
    assert exit_status == 1
    assert (
        "kept: named by 1 simulation, 2 reports and 0 household calculations"
    ) in output
    assert "1 stored policy still sets a model assumption." in output


def test_a_listing_with_a_refused_copy_fails(capsys) -> None:
    factory = RecordingFactory(
        FakeSplitter(
            (
                _split(
                    applied=False,
                    refusal_reason=PolicyCopyRefusalReason.CONFLICTING_DYNAMIC_VALUES,
                ),
            )
        )
    )

    exit_status = split_v2_policy_copies.main([], splitter_factory=factory)

    output = capsys.readouterr().out
    assert exit_status == 1
    assert f"Policy copy {OLD_COPY_ID}" in output
    assert "would be refused" in output
    assert "conflicting_dynamic_values" in output


def test_a_listing_with_a_copy_to_keep_fails(capsys) -> None:
    factory = RecordingFactory(
        FakeSplitter(
            (
                _split(
                    applied=False,
                    outcome=PolicyCopyOutcome.KEPT,
                    references=CopyReferences(
                        simulations=1, reports=0, household_jobs=0
                    ),
                ),
            )
        )
    )

    assert split_v2_policy_copies.main([], splitter_factory=factory) == 1
    assert "would be kept" in capsys.readouterr().out


def test_the_command_says_when_no_policy_sets_a_model_assumption(capsys) -> None:
    factory = RecordingFactory(FakeSplitter(()))

    exit_status = split_v2_policy_copies.main([], splitter_factory=factory)

    assert exit_status == 0
    assert "No stored policy sets a model assumption." in capsys.readouterr().out


def test_the_command_needs_its_own_database_url(monkeypatch) -> None:
    monkeypatch.delenv(V2_POLICY_COPY_SPLIT_DATABASE_URL, raising=False)

    with (
        pytest.raises(V2ConfigurationError, match=V2_POLICY_COPY_SPLIT_DATABASE_URL),
        split_v2_policy_copies.splitter_on_temporary_role(writable=False),
    ):
        pass


@pytest.mark.parametrize(
    ("run", "expected_opener"),
    [("listing", "unpooled_v2_read_only_sessions"), ("apply", "unpooled_v2_sessions")],
)
def test_the_command_lists_read_only_and_bounds_its_waits(
    monkeypatch, run: str, expected_opener: str
) -> None:
    """The listing's transactions are READ ONLY, and no wait lasts indefinitely.

    The URL gains a connection timeout, and a lock and statement timeout, so
    a lock wait can't hold the copy's row lock indefinitely.
    """
    from policyengine_api.data.v2 import database

    project_ref = "abcdefghijklmnopqrst"
    monkeypatch.setenv(
        V2_POLICY_COPY_SPLIT_DATABASE_URL,
        f"postgresql+psycopg://policy-copy-split:password@db.{project_ref}."
        "supabase.co:5432/postgres?sslmode=require",
    )
    monkeypatch.setenv(V2_SUPABASE_PROJECT_REF, project_ref)
    monkeypatch.setenv(V2_SUPABASE_ENVIRONMENT, "staging")
    opened: list[tuple[str, object]] = []

    def recording_opener(name: str):
        @contextmanager
        def open_sessions(url):
            opened.append((name, url))
            yield sessionmaker()

        return open_sessions

    for name in ("unpooled_v2_read_only_sessions", "unpooled_v2_sessions"):
        monkeypatch.setattr(database, name, recording_opener(name))

    with split_v2_policy_copies.splitter_on_temporary_role(
        writable=run == "apply"
    ) as splitter:
        assert hasattr(splitter, "split_policy_copies")

    [(opener, url)] = opened
    assert opener == expected_opener
    assert url.query["connect_timeout"] == "10"
    # Shorter than PostgreSQL's default one-second deadlock_timeout, so in a
    # lock cycle with a live write the split's wait ends first.
    assert url.query["options"] == "-c lock_timeout=500 -c statement_timeout=60000"
    assert url.query["sslmode"] == "require"


def test_the_command_refuses_unknown_arguments() -> None:
    with pytest.raises(SystemExit) as exit_info:
        split_v2_policy_copies.main(
            ["--dry-run"], splitter_factory=RecordingFactory(FakeSplitter(()))
        )

    assert exit_info.value.code == 2


def test_loading_the_command_leaves_the_observability_runtime_unbuilt() -> None:
    """The command and what its splitter factory loads mustn't build the runtime.

    Importing ``policyengine_api.observability`` builds the process-wide
    runtime, which adds a root log handler and writes to the command's output.
    """
    import_check = (
        "import sys\n"
        "import scripts.split_v2_policy_copies\n"
        "import policyengine_api.data.v2.database\n"
        "import policyengine_api.services.v2.policy_copy_split.database_session\n"
        "import policyengine_api.services.v2.policy_copy_split.services\n"
        "loaded = 'policyengine_api.observability' in sys.modules\n"
        "assert not loaded, 'the observability runtime was imported'\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", import_check],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
