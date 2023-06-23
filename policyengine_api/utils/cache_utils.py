import json
import flask
import logging

# keep it fast, adding overhead to try to add some minor chance of a cache hit is not worth it.
def make_cache_key(*args, **kwargs):
    data = ''
    if flask.request.content_type == "application/json":
        data = flask.request.get_json()
    elif flask.request.content_type in ["application/x-www-form-urlencoded", "multipart/form-data"]:
        data = flask.request.form.to_dict()
    if data != '':
        data = json.dumps(data, separators=('',''))
        
    cache_key = str(hash(flask.request.full_path + data))
    logging.basicConfig(level=logging.DEBUG)
    logging.getLogger().debug("PATH:" + flask.request.full_path + ", CACHE_KEY:" + cache_key)
    return cache_key