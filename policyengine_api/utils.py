import hashlib
import base64
import dpath
import numpy as np
from policyengine_core.parameters import ParameterNode
from policyengine_core.reforms import Reform
from policyengine_core.periods import instant


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


def get_safe_json(value):
    if isinstance(value, (int, float)):
        if value == np.inf:
            return ".inf"
        elif value == -np.inf:
            return "-.inf"
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return {k: get_safe_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [get_safe_json(v) for v in value]
    return None


def create_reform(reform_json: dict):
    """
    The reform JSON will be in the form:
    { parameters.tax.income_tax.rate: { 2022-01-01.2023-01-01: 0.5, ... }, ... }
    """

    def modify_parameters(parameters: ParameterNode) -> ParameterNode:
        for path, values in reform_json.items():
            node = parameters
            for step in path.split("."):
                node = node.children[step]
            for period, value in values.items():
                start, end = period.split(".")
                node.update(
                    start=instant(start),
                    stop=instant(end),
                    value=float(value),
                )

        return parameters

    class reform(Reform):
        def apply(self):
            self.modify_parameters(modify_parameters)

    return reform