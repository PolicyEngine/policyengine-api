"""Tools for caching API responses."""

import json
import logging
import flask


def make_cache_key(*args, **kwargs):
    # pylint: disable=unused-argument
    """make a hash to uniquely identify a cache entry.
    keep it fast, adding overhead to try to add some minor chance of a
    cache hit is not worth it.
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

    cache_key = str(hash(flask.request.full_path + data))
    logging.basicConfig(level=logging.DEBUG)
    logging.getLogger().debug(
        "PATH: %s, CACHE_KEY: %s", flask.request.full_path, cache_key
    )
    return cache_key
