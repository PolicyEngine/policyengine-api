# PR 2 FastAPI Shell Runbook

PR 2 adds an ASGI FastAPI shell around the existing Flask API. It is a
compatibility step only.

## Included

- Native FastAPI `GET /health`.
- Flask fallback for all existing API v1 routes through WSGI middleware.
- ASGI parity tests for current app-v2 contract routes.
- Local Uvicorn run command.

## Not Included

- No production traffic shift.
- No Cloud Run deployment.
- No native FastAPI route migration beyond `GET /health`.
- No Supabase, Alembic, SQLAlchemy, or Modal compute changes.

## Local Smoke

Run:

```bash
FLASK_DEBUG=1 uvicorn policyengine_api.asgi:app --port 8000
```

Smoke-check:

```bash
curl -i http://localhost:8000/health
curl -i http://localhost:8000/readiness-check
curl -i http://localhost:8000/liveness-check
curl -i http://localhost:8000/zz/metadata
```

Expected behavior:

- `/health` returns FastAPI JSON: `{"status":"healthy"}`.
- `/readiness-check` and `/liveness-check` return existing Flask text `OK`.
- Existing v1 routes continue to use Flask fallback behavior.
