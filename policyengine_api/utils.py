import hashlib
import base64
import dpath
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


def get_requested_computations(household: dict):
    requested_computations = dpath.util.search(
        household,
        "*/*/*/*",
        afilter=lambda t: t is None,
        yielded=True,
    )
    requested_computation_data = []

    for computation in requested_computations:
        path = computation[0]
        entity_plural, entity_id, variable_name, period = path.split("/")
        requested_computation_data.append(
            (entity_plural, entity_id, variable_name, period)
        )

    return requested_computation_data


def sanitise_parameter_value(value):
    if isinstance(value, (int, float)):
        if value == np.inf:
            return ".inf"
        elif value == -np.inf:
            return "-.inf"
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return {k: sanitise_parameter_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitise_parameter_value(v) for v in value]
    return None
