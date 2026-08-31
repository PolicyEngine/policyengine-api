# Cloud Run container guidance

The release workflow builds `gcp/cloud_run/Dockerfile` and deploys the resulting
image to the staging and production Cloud Run services. The image runs Gunicorn
through `gcp/cloud_run/start.sh`; it does not install or launch Redis and has no
localhost cache fallback.

Cloud Run injects the database password, external-service credentials,
Memorystore URL, and Memorystore CA through revision-specific Secret Manager
bindings. Required cache settings are `RUNTIME_CACHE_MODE`, `RUNTIME_CACHE_URL`,
`RUNTIME_CACHE_CA_CERT`, `RUNTIME_CACHE_ENVIRONMENT`, and
`RUNTIME_CACHE_SERVICE`; deployed mode fails closed when they are incomplete.
Secret values and temporary credential files must never enter the build context
or image layers.

Local development uses an explicitly launched Redis-compatible process and an
explicit durable development database. For example:

```sh
export RUNTIME_CACHE_MODE=local
export RUNTIME_CACHE_URL=redis://127.0.0.1:6379/0
export RUNTIME_CACHE_ENVIRONMENT=local-dev
export RUNTIME_CACHE_SERVICE=api
```

Build the production container locally with:

```sh
docker build -f gcp/cloud_run/Dockerfile -t policyengine-api-cloud-run:test .
```

Publishing and deployment remain release-workflow responsibilities. Do not
manually push an image as a substitute for the staged release sequence.
