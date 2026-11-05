"""Characterization of the in-memory fake's compare-and-delete script support."""

import pytest

from policyengine_api.runtime_cache.fake import InMemoryCacheBackend
from policyengine_api.runtime_cache.reform_impacts import DELETE_UNCHANGED_RECORD


def test_compare_and_delete_removes_only_a_matching_value():
    backend = InMemoryCacheBackend()
    backend.set("claim", "owner")

    assert backend.eval("ignored script", 1, "claim", "contender") == 0
    assert backend.get("claim") == "owner"
    assert backend.eval("ignored script", 1, "claim", "owner") == 1
    assert backend.get("claim") is None
    assert backend.eval("ignored script", 1, "claim", "owner") == 0


@pytest.mark.parametrize(
    ("key_count", "keys_and_arguments"),
    [
        (2, ("claim", "owner")),
        (0, ("claim", "owner")),
        (1, ("claim",)),
        (1, ("claim", "owner", "extra")),
    ],
)
def test_other_script_shapes_are_refused(key_count, keys_and_arguments):
    backend = InMemoryCacheBackend()

    with pytest.raises(
        ValueError, match="fake supports one-key compare-and-delete only"
    ):
        backend.eval("ignored script", key_count, *keys_and_arguments)


def _backend_with_indexed_record() -> InMemoryCacheBackend:
    backend = InMemoryCacheBackend()
    backend.set("record", "failure")
    backend.zadd("scope-index", {"record": 1.0, "other-record": 2.0})
    backend.zadd("recent-index", {"record": 1.0, "other-record": 2.0})
    return backend


def test_record_delete_removes_an_unchanged_record_and_its_index_entries():
    backend = _backend_with_indexed_record()
    keys = ("record", "scope-index", "recent-index")

    assert backend.eval(DELETE_UNCHANGED_RECORD, 3, *keys, "rewritten") == 0
    assert backend.get("record") == "failure"
    assert backend.zrevrange("scope-index", 0, -1) == ["other-record", "record"]
    assert backend.eval(DELETE_UNCHANGED_RECORD, 3, *keys, "failure") == 1
    assert backend.get("record") is None
    assert backend.zrevrange("scope-index", 0, -1) == ["other-record"]
    assert backend.zrevrange("recent-index", 0, -1) == ["other-record"]
    assert backend.eval(DELETE_UNCHANGED_RECORD, 3, *keys, "failure") == 0


@pytest.mark.parametrize(
    ("key_count", "keys_and_arguments"),
    [
        (1, ("record", "failure")),
        (3, ("record", "scope-index", "recent-index")),
        (2, ("record", "scope-index", "failure")),
    ],
)
def test_record_delete_refuses_other_shapes(key_count, keys_and_arguments):
    backend = _backend_with_indexed_record()

    with pytest.raises(ValueError, match="three keys and one argument"):
        backend.eval(DELETE_UNCHANGED_RECORD, key_count, *keys_and_arguments)


def test_set_with_xx_writes_only_a_key_that_exists():
    backend = InMemoryCacheBackend()

    assert backend.set("record", "first", xx=True) is None
    assert backend.get("record") is None
    backend.set("record", "first")
    assert backend.set("record", "second", xx=True) is True
    assert backend.get("record") == "second"
