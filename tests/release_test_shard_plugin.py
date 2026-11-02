"""Pytest plugin that runs one shard of the release test suite.

.github/scripts/run_release_tests.sh loads it with ``-p
tests.release_test_shard_plugin`` in push.yml's release-tests job. After
collection it keeps only the tests in the files scripts/release_test_shards.py
assigns to this runner's shard (``RELEASE_TEST_SHARD_INDEX`` of
``RELEASE_TEST_SHARD_COUNT``), reports the rest as deselected, and writes what
it collected and kept to ``RELEASE_TEST_SHARD_REPORT_DIRECTORY`` for the
check-release-test-shards job.

It reads those settings once, when pytest configures it, and then removes them
and its own ``-p`` option from ``PYTEST_ADDOPTS`` in the process environment.
A test that runs pytest itself would otherwise load the plugin again in that
inner run, split the inner run's tests and replace this shard's report.
"""

from __future__ import annotations

import os
import shlex

import pytest

from scripts.release_test_shards import (
    REPORT_DIRECTORY_VARIABLE,
    SHARD_COUNT_VARIABLE,
    SHARD_INDEX_VARIABLE,
    ShardSettings,
    shard_node_ids,
    shard_settings,
    write_report,
)

PLUGIN_NAME = __name__
SHARD_SETTINGS_KEY = pytest.StashKey[ShardSettings]()


def pytest_configure(config: pytest.Config) -> None:
    """Read this shard's settings, then keep them from pytest runs tests start."""
    try:
        config.stash[SHARD_SETTINGS_KEY] = shard_settings(os.environ)
    except ValueError as error:
        raise pytest.UsageError(str(error)) from error
    _remove_shard_settings_from_environment()


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Keep only this shard's tests, after every other plugin has filtered them."""
    settings = config.stash[SHARD_SETTINGS_KEY]
    collected = [item.nodeid for item in items]
    selected_node_ids = set(shard_node_ids(collected, settings.index, settings.count))
    selected = [item for item in items if item.nodeid in selected_node_ids]
    deselected = [item for item in items if item.nodeid not in selected_node_ids]
    if deselected:
        config.hook.pytest_deselected(items=deselected)
    items[:] = selected
    write_report(settings, collected, [item.nodeid for item in selected])


def _remove_shard_settings_from_environment() -> None:
    """Remove the shard settings and this plugin's option from os.environ."""
    for variable in (
        SHARD_INDEX_VARIABLE,
        SHARD_COUNT_VARIABLE,
        REPORT_DIRECTORY_VARIABLE,
    ):
        os.environ.pop(variable, None)
    remaining_options = _options_without_this_plugin(
        shlex.split(os.environ.get("PYTEST_ADDOPTS", ""))
    )
    if remaining_options:
        os.environ["PYTEST_ADDOPTS"] = shlex.join(remaining_options)
    else:
        os.environ.pop("PYTEST_ADDOPTS", None)


def _options_without_this_plugin(options: list[str]) -> list[str]:
    """Return pytest ``options`` without the ones that load this plugin."""
    remaining: list[str] = []
    option_iterator = iter(options)
    for option in option_iterator:
        if option == "-p":
            plugin_name = next(option_iterator, None)
            if plugin_name != PLUGIN_NAME:
                remaining += [option] if plugin_name is None else [option, plugin_name]
        elif option != f"-p{PLUGIN_NAME}":
            remaining.append(option)
    return remaining
