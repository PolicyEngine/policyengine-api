"""Tools for caching API responses."""

import hashlib
import json
import logging
import flask


def make_cache_key(*args, **kwargs):
    # pylint: disable=unused-argument
    """make a hash to uniquely identify a cache entry.
    keep it fast, adding overhead to try to add some minor chance of a
    cache hit is not worth it.

    Use a cryptographic digest (SHA-256) rather than the builtin
    `hash()`, whose output depends on PYTHONHASHSEED and is therefore
    different across workers/restarts; that made same-input requests
    miss the cache in production.
    """
    data = ""
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
