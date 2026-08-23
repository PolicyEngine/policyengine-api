# Docker guidance

The deployment actions build Docker images and deploy them to Google App Engine. The docker images themselves are based off a starter image (to save each API docker image having to spend 5 minutes installing the same dependencies). The starter image is the `Dockerfile` in this directory.

Deployed API images run only Gunicorn. They do not install or launch Redis and
have no localhost cache fallback. Stage 8 revisions receive their environment's
Memorystore endpoint, AUTH value, and instance CA through revision-specific
Secret Manager wiring. Required runtime settings are `RUNTIME_CACHE_MODE`,
`RUNTIME_CACHE_URL`, `RUNTIME_CACHE_CA_CERT`, `RUNTIME_CACHE_ENVIRONMENT`, and
`RUNTIME_CACHE_SERVICE`; deployed mode fails closed when they are incomplete.

The App Engine image is environment-neutral. `app.yaml` receives non-secret
configuration and Secret Manager resource names only. Before Gunicorn starts,
`policyengine_api.app_engine_runtime` resolves the database password, GitHub
microdata token, OpenAI key, and Hugging Face token into the process environment
using the attached App Engine service account. Raw values and temporary secret
files must never enter the build context or image layers.

Local development uses an explicitly launched Redis-compatible process and an
explicit durable development database. For example:

```sh
export RUNTIME_CACHE_MODE=local
export RUNTIME_CACHE_URL=redis://127.0.0.1:6379/0
export RUNTIME_CACHE_ENVIRONMENT=local-dev
export RUNTIME_CACHE_SERVICE=api
```

To update the starter image:
* `python setup.py sdist` to build the python package
* `twine upload dist/*` to upload the package to pypi as `policyengine-api`
* `cd gcp`
* `docker build .`
* `docker images` to get the image id (the most recent one should be the one you just built)
* `docker tag <image id> policyengine/policyengine-api`
* `docker push policyengine/policyengine-api`
