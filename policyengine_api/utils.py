import hashlib
import base64
import dpath
import numpy as np
from flask import Response
from policyengine_core.parameters import ParameterNode
from policyengine_core.reforms import Reform
from policyengine_core.periods import instant
import json
import time
from policyengine_api.logging import log


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


def safe_endpoint(f):
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            return Response(
                response=json.dumps(dict(status="error", message=str(e))),
                status=500,
            )

    wrapper.__name__ = f.__name__

    return wrapper


def timed_endpoint(f):
    def wrapper(*args, **kwargs):
        start = time.time()
        response = f(*args, **kwargs)
        # response is a Python object, not a Flask response object
        # so we need to convert it to a Flask response object
        end = time.time()
        log(
            api="api",
            level="info",
            message=f"Request to {f.__name__} took {end - start:.2f} seconds",
        )
        return response

    wrapper.__name__ = f.__name__

    return wrapper
