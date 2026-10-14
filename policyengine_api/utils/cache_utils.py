"""Tools for caching API responses."""

import hashlib
import json
import logging
from typing import Any

import flask


def make_cache_key(*_args: object, **_kwargs: object) -> str:
    """Hash the current request's full path and JSON or form body into a cache key.

    The arguments are ignored. Keep it fast: adding overhead for a minor extra
    chance of a cache hit is not worth it.

    Use a cryptographic digest (SHA-256) rather than the builtin
    `hash()`, whose output depends on PYTHONHASHSEED and is therefore
    different across workers/restarts; that made same-input requests
    miss the cache in production.
    """
    data: Any = ""
    if flask.request.content_type == "application/json":
        data = flask.request.get_json()
    elif flask.request.content_type in [
        "application/x-www-form-urlencoded",
        "multipart/form-data",
    ]:
        data = flask.request.form.to_dict()
    if data != "":
        data = json.dumps(data, separators=("", ""))

    full_path = flask.request.full_path
    cache_key = hashlib.sha256((full_path + data).encode("utf-8")).hexdigest()
    logging.basicConfig(level=logging.DEBUG)
    logging.getLogger().debug(
        "PATH: %s, CACHE_KEY: %s", flask.request.full_path, cache_key
    )
    return cache_key
