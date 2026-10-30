"""Pytest plugin that runs one shard of the release test suite.

.github/scripts/run_release_tests.sh loads it with ``-p
tests.release_test_shard_plugin`` in push.yml's release-tests job. After
collection it keeps only the tests in the files scripts/release_test_shards.py
assigns to this runner's shard (``RELEASE_TEST_SHARD_INDEX`` of
``RELEASE_TEST_SHARD_COUNT``), reports the rest as deselected, and writes what
it collected and kept to ``RELEASE_TEST_SHARD_REPORT_DIRECTORY`` for the
check-release-test-shards job.
"""

from __future__ import annotations

import os

import pytest

from scripts.release_test_shards import shard_node_ids, shard_settings, write_report


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Keep only this shard's tests, after every other plugin has filtered them."""
    try:
        settings = shard_settings(os.environ)
    except ValueError as error:
        raise pytest.UsageError(str(error)) from error
    collected = [item.nodeid for item in items]
    selected_node_ids = set(shard_node_ids(collected, settings.index, settings.count))
    selected = [item for item in items if item.nodeid in selected_node_ids]
    deselected = [item for item in items if item.nodeid not in selected_node_ids]
    if deselected:
        config.hook.pytest_deselected(items=deselected)
    items[:] = selected
    write_report(settings, collected, [item.nodeid for item in selected])
