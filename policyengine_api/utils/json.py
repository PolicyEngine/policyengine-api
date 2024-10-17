import hashlib
import base64
import numpy as np


def make_hashable(o):
    if isinstance(o, (tuple, list)):
        return tuple((make_hashable(e) for e in o))

    if isinstance(o, dict):
        return tuple(sorted((k, make_hashable(v)) for k, v in o.items()))

    if isinstance(o, (set, frozenset)):
        return tuple(sorted(make_hashable(e) for e in o))

    return o


def hash_object(o):
    hasher = hashlib.sha256()
    hasher.update(repr(make_hashable(o)).encode())
    return base64.b64encode(hasher.digest()).decode()


def get_safe_json(value):
    # This function is used when constructing metadata,
    # which will be consumed by JS, hence Infinity, not .inf
    if isinstance(value, (int, float)):
        if value == np.inf:
            return "Infinity"
        elif value == -np.inf:
            return "-Infinity"
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return {k: get_safe_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [get_safe_json(v) for v in value]
    return None
