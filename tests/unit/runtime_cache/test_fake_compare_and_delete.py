"""Characterization of the in-memory fake's compare-and-delete script support."""

import pytest

from policyengine_api.runtime_cache.fake import InMemoryCacheBackend


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
