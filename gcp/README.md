# Docker guidance

The deployment actions build Docker images and deploy them to Google App Engine. The docker images themselves are based off a starter image (to save each API docker image having to spend 5 minutes installing the same dependencies). The starter image is the `Dockerfile` in this directory.

The App Engine API image installs `redis-server` and starts it through `gcp/policyengine_api/start.sh`. Redis is required at runtime for budget-window economy request caching and in-flight batch deduplication. The API reads `CACHE_REDIS_HOST`, `CACHE_REDIS_PORT`, and `CACHE_REDIS_DB`, defaulting to `127.0.0.1`, `6379`, and `0`.

To update the starter image:
* `python setup.py sdist` to build the python package
* `twine upload dist/*` to upload the package to pypi as `policyengine-api`
* `cd gcp`
* `docker build .`
* `docker images` to get the image id (the most recent one should be the one you just built)
* `docker tag <image id> policyengine/policyengine-api`
* `docker push policyengine/policyengine-api`
