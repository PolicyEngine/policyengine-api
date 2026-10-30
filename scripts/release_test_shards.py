"""Split the release test suite into shards, and check that each test ran once.

push.yml's release-tests job runs ``make test`` on ``RELEASE_TEST_SHARD_COUNT``
runners at once, one shard each. Every runner collects the whole suite, and the
pytest plugin in tests/release_test_shard_plugin.py keeps only the tests in the
files ``assign_files_to_shards`` gives its shard, ``RELEASE_TEST_SHARD_INDEX``
(1 to the count). A file's tests stay together, so its module- and class-scoped
fixtures are set up once.

Files are assigned heaviest first, each to the shard with the least weight so
far, ties going to the lower shard number; equal weights are taken in path
order. A file's weight is its measured seconds in ``MEASURED_FILE_SECONDS``, or
else its number of tests times ``SECONDS_PER_UNMEASURED_TEST``. The
assignment depends only on the collected files and their test counts, so every
runner that collects the same tests computes the same one, and each test runs
in exactly one shard. A weight that is out of date only makes the shards finish
less evenly.

Each runner writes what it collected and what it kept to
``RELEASE_TEST_SHARD_REPORT_DIRECTORY``. push.yml's check-release-test-shards
job downloads every shard's report and runs this module's ``check-coverage``
command, which fails unless every shard reported, all of them collected the same
tests, and each collected test was kept by exactly one shard.

Usage: python -m scripts.release_test_shards check-coverage --shard-count N DIR
where DIR holds one ``release-test-shard-<index>`` directory per shard.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

SHARD_INDEX_VARIABLE = "RELEASE_TEST_SHARD_INDEX"
SHARD_COUNT_VARIABLE = "RELEASE_TEST_SHARD_COUNT"
REPORT_DIRECTORY_VARIABLE = "RELEASE_TEST_SHARD_REPORT_DIRECTORY"
REPORT_DIRECTORY_PREFIX = "release-test-shard-"
SHARD_FILE = "shard.json"
COLLECTED_FILE = "collected.txt"
SELECTED_FILE = "selected.txt"
# How many problems of one kind check-coverage prints before it summarizes.
LISTED_PROBLEM_LIMIT = 20
# Seconds each file's tests took, setup and teardown included, in a local run of
# make test's paths with --durations=0 on 2026-10-29 (only files over 10
# seconds). Only the ratios matter.
MEASURED_FILE_SECONDS = {
    "tests/unit/test_country_spm.py": 166,
    "tests/unit/v2/test_import_side_effects.py": 152,
    "tests/unit/v2/test_user_policy_routes.py": 32,
    "tests/unit/test_asgi_factory.py": 29,
    "tests/unit/v2/test_user_route_auth.py": 27,
    "tests/unit/test_changelog_fragment_check.py": 24,
    "tests/unit/v2/test_household_routes.py": 19,
    "tests/unit/v2/test_user_household_routes.py": 17,
    "tests/unit/routes/test_canonical_spm.py": 15,
    "tests/unit/test_bundle_update_pins.py": 15,
    "tests/unit/data/test_v1_database_migration.py": 15,
    "tests/unit/routes/test_economy_spm_query.py": 15,
    "tests/to_refactor/api/test_api.py": 15,
    "tests/unit/routes/test_policy_dual_write_routes.py": 14,
    "tests/unit/libs/test_simulation_entrypoint.py": 14,
    "tests/unit/test_relock_pull_request_script.py": 13,
    "tests/unit/services/test_budget_window_cache.py": 13,
    "tests/contract/test_v1_route_contracts.py": 12,
    "tests/unit/test_stage6_native_metadata.py": 11,
}
# The mean time of a test in the other files, in the same run.
SECONDS_PER_UNMEASURED_TEST = 0.04


@dataclass(frozen=True)
class ShardSettings:
    """Which shard this runner runs, of how many, and where it reports."""

    index: int
    count: int
    report_directory: Path


@dataclass(frozen=True)
class ShardReport:
    """What one shard collected and kept, as its runner wrote them."""

    index: int
    count: int
    collected: tuple[str, ...]
    selected: tuple[str, ...]


def shard_settings(environ: Mapping[str, str]) -> ShardSettings:
    """Read the shard settings, raising ValueError when one is missing or wrong."""
    missing = [
        name
        for name in (
            SHARD_INDEX_VARIABLE,
            SHARD_COUNT_VARIABLE,
            REPORT_DIRECTORY_VARIABLE,
        )
        if not environ.get(name)
    ]
    if missing:
        msg = f"release test sharding needs {', '.join(missing)}"
        raise ValueError(msg)
    index_text = environ[SHARD_INDEX_VARIABLE]
    count_text = environ[SHARD_COUNT_VARIABLE]
    if not (index_text.isdigit() and count_text.isdigit()):
        msg = (
            f"{SHARD_INDEX_VARIABLE} and {SHARD_COUNT_VARIABLE} must be whole "
            f"numbers, not {index_text!r} and {count_text!r}"
        )
        raise ValueError(msg)
    index = int(index_text)
    count = int(count_text)
    if not 1 <= index <= count:
        msg = (
            f"{SHARD_INDEX_VARIABLE}={index} must be from 1 to "
            f"{SHARD_COUNT_VARIABLE}={count}"
        )
        raise ValueError(msg)
    return ShardSettings(
        index=index,
        count=count,
        report_directory=Path(environ[REPORT_DIRECTORY_VARIABLE]),
    )


def node_file(node_id: str) -> str:
    """Return the file a pytest node ID belongs to."""
    return node_id.split("::", 1)[0]


def file_weights(node_ids: Iterable[str]) -> dict[str, float]:
    """Return each collected file's weight, from MEASURED_FILE_SECONDS or its tests."""
    tests_per_file = Counter(node_file(node_id) for node_id in node_ids)
    return {
        path: MEASURED_FILE_SECONDS.get(path, test_count * SECONDS_PER_UNMEASURED_TEST)
        for path, test_count in tests_per_file.items()
    }


def assign_files_to_shards(
    weights: Mapping[str, float], shard_count: int
) -> dict[str, int]:
    """Return the shard (1 to ``shard_count``) each file of ``weights`` runs in."""
    if shard_count < 1:
        msg = f"there must be at least one shard, not {shard_count}"
        raise ValueError(msg)
    shard_totals = dict.fromkeys(range(1, shard_count + 1), 0.0)
    assignment = {}
    for path in sorted(weights, key=lambda path: (-weights[path], path)):
        lightest_shard = min(
            shard_totals, key=lambda shard: (shard_totals[shard], shard)
        )
        assignment[path] = lightest_shard
        shard_totals[lightest_shard] += weights[path]
    return assignment


def shard_node_ids(
    node_ids: Sequence[str], shard_index: int, shard_count: int
) -> list[str]:
    """Return the node IDs, in collection order, that shard ``shard_index`` runs."""
    assignment = assign_files_to_shards(file_weights(node_ids), shard_count)
    return [
        node_id for node_id in node_ids if assignment[node_file(node_id)] == shard_index
    ]


def write_report(
    settings: ShardSettings, collected: Sequence[str], selected: Sequence[str]
) -> None:
    """Write what this shard collected and kept to its report directory.

    Raise FileExistsError if the directory already has a report: a second
    pytest run in the same shard would otherwise replace the first one's.
    """
    settings.report_directory.mkdir(parents=True, exist_ok=True)
    try:
        with (settings.report_directory / SHARD_FILE).open(
            "x", encoding="utf-8"
        ) as shard_file:
            shard_file.write(
                json.dumps({"index": settings.index, "count": settings.count}) + "\n"
            )
    except FileExistsError as error:
        msg = (
            f"{settings.report_directory} already has a shard report; another "
            "pytest run in this shard wrote it. Remove the directory to run the "
            "shard again."
        )
        raise FileExistsError(msg) from error
    for file_name, node_ids in (
        (COLLECTED_FILE, collected),
        (SELECTED_FILE, selected),
    ):
        (settings.report_directory / file_name).write_text(
            "".join(f"{node_id}\n" for node_id in node_ids), encoding="utf-8"
        )


def read_report(report_directory: Path) -> ShardReport:
    """Read one shard's report, as write_report wrote it."""
    shard = json.loads((report_directory / SHARD_FILE).read_text(encoding="utf-8"))
    return ShardReport(
        index=shard["index"],
        count=shard["count"],
        collected=tuple(
            (report_directory / COLLECTED_FILE).read_text(encoding="utf-8").splitlines()
        ),
        selected=tuple(
            (report_directory / SELECTED_FILE).read_text(encoding="utf-8").splitlines()
        ),
    )


def _listed(kind: str, node_ids: Sequence[str]) -> list[str]:
    problems = [f"{kind}: {node_id}" for node_id in node_ids[:LISTED_PROBLEM_LIMIT]]
    if len(node_ids) > LISTED_PROBLEM_LIMIT:
        problems.append(f"{kind}: {len(node_ids) - LISTED_PROBLEM_LIMIT} more")
    return problems


def coverage_problems(
    reports: Mapping[int, ShardReport], shard_count: int
) -> list[str]:
    """Return why the shards did not run each collected test exactly once."""
    problems = [
        f"shard {index} of {shard_count} did not report"
        for index in range(1, shard_count + 1)
        if index not in reports
    ]
    for index, report in sorted(reports.items()):
        if (report.index, report.count) != (index, shard_count):
            problems.append(
                f"the report for shard {index} of {shard_count} says shard "
                f"{report.index} of {report.count}"
            )
    if problems:
        return problems
    collected = reports[1].collected
    for index, report in sorted(reports.items()):
        if set(report.collected) != set(collected):
            problems.append(
                f"shard {index} collected different tests from shard 1: "
                f"{len(set(report.collected) - set(collected))} more, "
                f"{len(set(collected) - set(report.collected))} fewer"
            )
    runs_per_test = Counter(
        node_id for report in reports.values() for node_id in report.selected
    )
    problems += _listed(
        "collected but run by no shard",
        [node_id for node_id in collected if node_id not in runs_per_test],
    )
    problems += _listed(
        "run by more than one shard",
        sorted(node_id for node_id, runs in runs_per_test.items() if runs > 1),
    )
    problems += _listed(
        "run but not collected",
        sorted(set(runs_per_test) - set(collected)),
    )
    return problems


def check_coverage(report_root: Path, shard_count: int) -> list[str]:
    """Read every shard's report under ``report_root`` and return the problems."""
    reports = {}
    for index in range(1, shard_count + 1):
        report_directory = report_root / f"{REPORT_DIRECTORY_PREFIX}{index}"
        if (report_directory / SHARD_FILE).exists():
            reports[index] = read_report(report_directory)
    return coverage_problems(reports, shard_count)


def main(argv: Sequence[str] | None = None) -> int:
    """Run ``check-coverage`` and return the shell status."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    coverage_parser = commands.add_parser("check-coverage")
    coverage_parser.add_argument("--shard-count", type=int, required=True)
    coverage_parser.add_argument("report_root", type=Path)
    arguments = parser.parse_args(argv)
    problems = check_coverage(arguments.report_root, arguments.shard_count)
    for problem in problems:
        print(f"::error::{problem}")
    if problems:
        return 1
    reports = [
        read_report(arguments.report_root / f"{REPORT_DIRECTORY_PREFIX}{index}")
        for index in range(1, arguments.shard_count + 1)
    ]
    print(
        f"Each of the {len(reports[0].collected)} collected release tests ran in "
        f"exactly one of {arguments.shard_count} shards: "
        + ", ".join(
            f"shard {report.index} ran {len(report.selected)}" for report in reports
        )
        + "."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
