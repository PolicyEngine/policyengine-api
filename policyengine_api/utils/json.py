"""Content hashing and JSON-safe conversion of policy, household and metadata values."""

from __future__ import annotations

import base64
import hashlib
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from policyengine_api.json_types import JSONValue


def make_hashable(
    o: object,
) -> Any:  # noqa: ANN401  # returns scalars unchanged, and callers sort them
    """Convert nested lists, dicts and sets into tuples, sorting dict items and sets.

    Equal values therefore convert identically whatever their key or member order.
    """
    if isinstance(o, (tuple, list)):
        return tuple(make_hashable(e) for e in o)

    if isinstance(o, dict):
        return tuple(sorted((k, make_hashable(v)) for k, v in o.items()))

    if isinstance(o, (set, frozenset)):
        return tuple(sorted(make_hashable(e) for e in o))

    return o


def hash_object(o: object) -> str:
    """Return a base64 SHA-256 digest of a value that ignores dict key order.

    It is the stored policy and household hash, and keys cached calculations.
    """
    hasher = hashlib.sha256()
    hasher.update(repr(make_hashable(o)).encode())
    return base64.b64encode(hasher.digest()).decode()


def get_safe_json(value: object) -> JSONValue:
    """Return a JSON-safe copy of a metadata value, writing infinities as strings.

    Values of any other type (dates, None, objects) become None.
    """
    # This function is used when constructing metadata,
    # which will be consumed by JS, hence Infinity, not .inf
    if isinstance(value, (int, float)):
        if value == np.inf:
            return "Infinity"
        if value == -np.inf:
            return "-Infinity"
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return {k: get_safe_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [get_safe_json(v) for v in value]
    return None
