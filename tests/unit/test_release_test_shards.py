"""Tests for the release test shards: the split, the plugin and the coverage check.

push.yml's release-tests job runs make test on six runners, one shard each
(scripts/release_test_shards.py, tests/release_test_shard_plugin.py), and
check-release-test-shards fails unless each collected test ran in exactly one.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from scripts import release_test_shards
from tests.unit.cloud_run_deploy_support import (
    REPO,
    job_needs,
    job_step,
    push_workflow_jobs,
)

if TYPE_CHECKING:
    from pathlib import Path

SHARD_COUNT = 6
NODE_IDS = [
    "tests/unit/test_alpha.py::test_one",
    "tests/unit/test_alpha.py::test_two",
    "tests/unit/test_beta.py::test_one",
    "tests/unit/test_gamma.py::TestGroup::test_one[case-a]",
    "tests/unit/test_gamma.py::TestGroup::test_one[case-b]",
    "tests/unit/test_delta.py::test_one",
    "tests/unit/test_country_spm.py::test_heavy",
]


def _make_test_paths() -> list[str]:
    """Return the paths make test passes to pytest."""
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")
    recipe = makefile[makefile.index("\ntest:\n") :]
    pytest_line = next(line for line in recipe.splitlines() if " -m pytest " in line)
    arguments = pytest_line.split(" -m pytest ", 1)[1].split()
    return [argument for argument in arguments if argument.startswith("tests/")]


def _make_test_files() -> list[str]:
    """Return the test files under make test's paths, without importing them."""
    test_files = []
    for test_path in _make_test_paths():
        path = REPO / test_path
        if path.is_file():
            test_files.append(test_path)
            continue
        test_files += [
            str(found.relative_to(REPO))
            for found in sorted(path.rglob("test_*.py"))
            if "__pycache__" not in found.parts
        ]
    return test_files


# --- The split ------------------------------------------------------------------


def test_every_node_id_runs_in_exactly_one_shard():
    shards = [
        release_test_shards.shard_node_ids(NODE_IDS, shard_index, SHARD_COUNT)
        for shard_index in range(1, SHARD_COUNT + 1)
    ]
    assigned = [node_id for shard in shards for node_id in shard]

    assert sorted(assigned) == sorted(NODE_IDS)
    assert len(assigned) == len(set(assigned))


def test_a_files_tests_stay_in_one_shard_in_collection_order():
    for shard_index in range(1, SHARD_COUNT + 1):
        shard = release_test_shards.shard_node_ids(NODE_IDS, shard_index, SHARD_COUNT)
        assert shard == [node_id for node_id in NODE_IDS if node_id in shard]
        gamma_tests = [node_id for node_id in shard if "test_gamma.py" in node_id]
        assert gamma_tests in ([], NODE_IDS[3:5])


def test_the_split_depends_only_on_the_collected_tests():
    reordered = list(reversed(NODE_IDS))

    for shard_index in range(1, SHARD_COUNT + 1):
        assert set(
            release_test_shards.shard_node_ids(NODE_IDS, shard_index, SHARD_COUNT)
        ) == set(
            release_test_shards.shard_node_ids(reordered, shard_index, SHARD_COUNT)
        )


def test_files_go_heaviest_first_to_the_lightest_shard():
    weights = {"a.py": 10.0, "b.py": 7.0, "c.py": 4.0, "d.py": 4.0, "e.py": 2.0}

    assert release_test_shards.assign_files_to_shards(weights, 2) == {
        "a.py": 1,
        "b.py": 2,
        "c.py": 2,
        "d.py": 1,
        "e.py": 2,
    }


def test_a_measured_file_weighs_its_seconds_and_another_its_tests():
    weights = release_test_shards.file_weights(NODE_IDS)

    assert (
        weights["tests/unit/test_country_spm.py"]
        == (release_test_shards.MEASURED_FILE_SECONDS["tests/unit/test_country_spm.py"])
    )
    assert weights["tests/unit/test_gamma.py"] == pytest.approx(
        2 * release_test_shards.SECONDS_PER_UNMEASURED_TEST
    )


def test_every_make_test_file_is_assigned_to_exactly_one_of_six_shards():
    test_files = _make_test_files()
    assignment = release_test_shards.assign_files_to_shards(
        release_test_shards.file_weights(test_files), SHARD_COUNT
    )

    assert sorted(assignment) == sorted(test_files)
    assert set(assignment.values()) == set(range(1, SHARD_COUNT + 1))


def test_every_measured_file_is_a_make_test_file():
    # A renamed or removed file would keep a weight nothing uses; measure again.
    assert set(release_test_shards.MEASURED_FILE_SECONDS) <= set(_make_test_files())


@pytest.mark.parametrize(
    ("environ", "message"),
    [
        ({}, "needs RELEASE_TEST_SHARD_INDEX, RELEASE_TEST_SHARD_COUNT"),
        (
            {
                "RELEASE_TEST_SHARD_INDEX": "7",
                "RELEASE_TEST_SHARD_COUNT": "6",
                "RELEASE_TEST_SHARD_REPORT_DIRECTORY": "reports",
            },
            "RELEASE_TEST_SHARD_INDEX=7 must be from 1 to RELEASE_TEST_SHARD_COUNT=6",
        ),
        (
            {
                "RELEASE_TEST_SHARD_INDEX": "one",
                "RELEASE_TEST_SHARD_COUNT": "6",
                "RELEASE_TEST_SHARD_REPORT_DIRECTORY": "reports",
            },
            "must be whole numbers",
        ),
    ],
)
def test_shard_settings_refuse_a_missing_or_impossible_shard(environ, message):
    with pytest.raises(ValueError, match=re.escape(message)):
        release_test_shards.shard_settings(environ)


# --- The coverage check -----------------------------------------------------------


def _report(index: int, selected: list[str], collected: list[str] | None = None):
    return release_test_shards.ShardReport(
        index=index,
        count=2,
        collected=tuple(NODE_IDS if collected is None else collected),
        selected=tuple(selected),
    )


def test_shards_that_run_each_collected_test_once_pass():
    reports = {1: _report(1, NODE_IDS[:3]), 2: _report(2, NODE_IDS[3:])}

    assert release_test_shards.coverage_problems(reports, 2) == []


def test_a_test_no_shard_ran_fails_the_check():
    reports = {1: _report(1, NODE_IDS[:3]), 2: _report(2, NODE_IDS[4:])}

    assert release_test_shards.coverage_problems(reports, 2) == [
        f"collected but run by no shard: {NODE_IDS[3]}"
    ]


def test_a_test_two_shards_ran_fails_the_check():
    reports = {1: _report(1, NODE_IDS[:4]), 2: _report(2, NODE_IDS[3:])}

    assert release_test_shards.coverage_problems(reports, 2) == [
        f"run by more than one shard: {NODE_IDS[3]}"
    ]


def test_shards_that_collected_different_tests_fail_the_check():
    reports = {
        1: _report(1, NODE_IDS[:3]),
        2: _report(2, NODE_IDS[3:-1], collected=NODE_IDS[:-1]),
    }

    assert release_test_shards.coverage_problems(reports, 2) == [
        "shard 2 collected different tests from shard 1: 0 more, 1 fewer",
        f"collected but run by no shard: {NODE_IDS[-1]}",
    ]


def test_a_shard_that_did_not_report_fails_the_check():
    assert release_test_shards.coverage_problems({1: _report(1, NODE_IDS)}, 2) == [
        "shard 2 of 2 did not report"
    ]


# --- The plugin, end to end -------------------------------------------------------


def _write_test_suite(root: Path) -> None:
    """Write 5 test files of 3 tests each under ``root``/sample_tests."""
    (root / "sample_tests").mkdir()
    for file_index in range(5):
        test_functions = "".join(
            f"def test_{test_index}():\n    pass\n\n\n" for test_index in range(3)
        )
        (root / "sample_tests" / f"test_file_{file_index}.py").write_text(
            test_functions
        )


def _run_shard(root: Path, report_root: Path, shard_index: int, shard_count: int):
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "tests.release_test_shard_plugin",
            "-p",
            "no:cacheprovider",
            "--rootdir",
            str(root),
            "-q",
            str(root / "sample_tests"),
        ],
        cwd=root,
        env={
            **os.environ,
            "PYTHONPATH": str(REPO),
            "RELEASE_TEST_SHARD_INDEX": str(shard_index),
            "RELEASE_TEST_SHARD_COUNT": str(shard_count),
            "RELEASE_TEST_SHARD_REPORT_DIRECTORY": str(
                report_root / f"release-test-shard-{shard_index}"
            ),
        },
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_plugin_runs_each_test_in_exactly_one_shard(tmp_path: Path):
    suite_root = tmp_path / "suite"
    suite_root.mkdir()
    _write_test_suite(suite_root)
    report_root = tmp_path / "reports"
    shard_count = 3

    results = [
        _run_shard(suite_root, report_root, shard_index, shard_count)
        for shard_index in range(1, shard_count + 1)
    ]
    coverage = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.release_test_shards",
            "check-coverage",
            "--shard-count",
            str(shard_count),
            str(report_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )

    for result in results:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "deselected" in result.stdout
    assert coverage.returncode == 0, coverage.stdout + coverage.stderr
    assert "Each of the 15 collected release tests ran in exactly one of 3 shards" in (
        coverage.stdout
    )


def test_the_coverage_check_fails_when_a_shard_did_not_report(tmp_path: Path):
    suite_root = tmp_path / "suite"
    suite_root.mkdir()
    _write_test_suite(suite_root)
    report_root = tmp_path / "reports"
    _run_shard(suite_root, report_root, 1, 2)

    coverage = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.release_test_shards",
            "check-coverage",
            "--shard-count",
            "2",
            str(report_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )

    assert coverage.returncode == 1
    assert "::error::shard 2 of 2 did not report" in coverage.stdout


def test_the_plugin_refuses_to_run_without_shard_settings(tmp_path: Path):
    suite_root = tmp_path / "suite"
    suite_root.mkdir()
    _write_test_suite(suite_root)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "tests.release_test_shard_plugin",
            "-p",
            "no:cacheprovider",
            "--rootdir",
            str(suite_root),
            str(suite_root / "sample_tests"),
        ],
        cwd=suite_root,
        env={
            name: value
            for name, value in {**os.environ, "PYTHONPATH": str(REPO)}.items()
            if not name.startswith("RELEASE_TEST_SHARD_")
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "release test sharding needs RELEASE_TEST_SHARD_INDEX" in (
        result.stdout + result.stderr
    )


INNER_PYTEST_TEST = """
import os
import subprocess
import sys


def test_a_pytest_run_this_test_starts_is_not_split():
    inherited_shard_settings = [
        name for name in os.environ if name.startswith("RELEASE_TEST_SHARD_")
    ]
    assert inherited_shard_settings == []
    assert "release_test_shard_plugin" not in os.environ.get("PYTEST_ADDOPTS", "")
    inner_run = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "--collect-only",
            "-q",
            "inner_tests",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert inner_run.returncode == 0, inner_run.stdout + inner_run.stderr
    assert "1 test collected" in inner_run.stdout
"""


def _write_test_suite_that_starts_pytest(root: Path) -> None:
    """Write the sample suite plus a test that runs pytest on inner_tests itself.

    The outer run doesn't collect inner_tests, just as make test doesn't collect
    the live staging tests that
    test_live_staging_tests_get_one_pytest_worker_each collects in its own
    pytest process.
    """
    _write_test_suite(root)
    (root / "sample_tests" / "test_starts_pytest.py").write_text(INNER_PYTEST_TEST)
    (root / "inner_tests").mkdir()
    (root / "inner_tests" / "test_inner.py").write_text("def test_inner():\n    pass\n")


def _run_shard_as_run_release_tests_does(
    root: Path, report_root: Path, shard_index: int, shard_count: int
):
    """Run one shard with the plugin loaded through PYTEST_ADDOPTS."""
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "--rootdir",
            str(root),
            "-q",
            str(root / "sample_tests"),
        ],
        cwd=root,
        env={
            **os.environ,
            "PYTHONPATH": str(REPO),
            "PYTEST_ADDOPTS": "-p tests.release_test_shard_plugin",
            "RELEASE_TEST_SHARD_INDEX": str(shard_index),
            "RELEASE_TEST_SHARD_COUNT": str(shard_count),
            "RELEASE_TEST_SHARD_REPORT_DIRECTORY": str(
                report_root / f"release-test-shard-{shard_index}"
            ),
        },
        capture_output=True,
        text=True,
        check=False,
    )


def test_a_pytest_run_that_a_test_starts_runs_without_the_split(tmp_path: Path):
    suite_root = tmp_path / "suite"
    suite_root.mkdir()
    _write_test_suite_that_starts_pytest(suite_root)
    report_root = tmp_path / "reports"
    shard_count = 3

    results = [
        _run_shard_as_run_release_tests_does(
            suite_root, report_root, shard_index, shard_count
        )
        for shard_index in range(1, shard_count + 1)
    ]
    coverage = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.release_test_shards",
            "check-coverage",
            "--shard-count",
            str(shard_count),
            str(report_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )

    # The inner pytest run neither splits its own tests nor replaces the
    # shard's report, so every shard passes and the reports cover the outer
    # run's 16 tests.
    for result in results:
        assert result.returncode == 0, result.stdout + result.stderr
    assert coverage.returncode == 0, coverage.stdout + coverage.stderr
    assert "Each of the 16 collected release tests ran in exactly one of 3 shards" in (
        coverage.stdout
    )


def test_a_shard_report_is_never_replaced(tmp_path: Path):
    settings = release_test_shards.ShardSettings(
        index=1, count=2, report_directory=tmp_path / "release-test-shard-1"
    )
    release_test_shards.write_report(
        settings, ["tests/unit/test_alpha.py::test_one"], []
    )

    with pytest.raises(FileExistsError, match="already has a shard report"):
        release_test_shards.write_report(
            settings, ["tests/unit/test_beta.py::test_one"], []
        )

    report = release_test_shards.read_report(settings.report_directory)
    assert report.collected == ("tests/unit/test_alpha.py::test_one",)


# --- push.yml -------------------------------------------------------------------


def test_the_release_tests_run_in_six_shards_that_report_what_they_ran():
    release_tests = push_workflow_jobs()["release-tests"]
    run_step = job_step(release_tests, "Run release tests")
    upload_step = job_step(
        release_tests, "Upload the tests this shard collected and ran"
    )

    assert release_tests["strategy"]["matrix"]["shard_index"] == list(
        range(1, SHARD_COUNT + 1)
    )
    assert release_tests["strategy"]["fail-fast"] is False
    assert run_step["env"]["RELEASE_TEST_SHARD_INDEX"] == "${{ matrix.shard_index }}"
    assert run_step["env"]["RELEASE_TEST_SHARD_COUNT"] == str(SHARD_COUNT)
    report_directory = run_step["env"]["RELEASE_TEST_SHARD_REPORT_DIRECTORY"]
    assert upload_step["uses"] == "actions/upload-artifact@v4"
    assert upload_step["with"] == {
        "name": "release-test-shard-${{ matrix.shard_index }}",
        "path": report_directory,
        "if-no-files-found": "error",
        "retention-days": 7,
    }


def test_the_staging_deploy_needs_every_release_test_to_have_run_once():
    jobs = push_workflow_jobs()
    shard_check = jobs["check-release-test-shards"]
    download_step = job_step(shard_check, "Download every shard's report")
    coverage_step = job_step(
        shard_check, "Check that every release test ran in exactly one shard"
    )

    assert job_needs(shard_check) == ["release-tests"]
    assert "needs.release-tests.result == 'success'" in shard_check["if"]
    assert download_step["uses"] == "actions/download-artifact@v4"
    assert download_step["with"]["pattern"] == "release-test-shard-*"
    assert coverage_step["run"] == (
        "python -m scripts.release_test_shards check-coverage "
        f"--shard-count {SHARD_COUNT} "
        f'"{download_step["with"]["path"]}"'
    )
    assert {"release-tests", "check-release-test-shards"} <= set(
        job_needs(jobs["deploy-cloud-run-staging"])
    )


def test_run_release_tests_loads_the_shard_plugin():
    script = (REPO / ".github/scripts/run_release_tests.sh").read_text(encoding="utf-8")

    assert "-p tests.release_test_shard_plugin" in script
    for variable in (
        "RELEASE_TEST_SHARD_INDEX",
        "RELEASE_TEST_SHARD_COUNT",
        "RELEASE_TEST_SHARD_REPORT_DIRECTORY",
    ):
        assert f"${{{variable}:?" in script
