# PR 1 Migration Baseline Runbook

> Historical record — describes the pipeline as it was when this PR landed.
> Current behavior: see [`../cloud-run-operations.md`](../cloud-run-operations.md).

PR 1 does not shift traffic or change API behavior. Before PR 2 starts, capture
baseline production or staging metrics so later cutovers can compare against the
same surface.

## Scope

- Included: current API v1 route contracts, current simulation gateway contract,
  app-v2 workflow contract registry, no-op migration flags, migration-context
  logging, and opt-in baseline capture.
- Not included: FastAPI shell, Cloud Run deployment, Supabase, Alembic, route
  rewrites, simulation facade, v2-alpha Modal workers, or app-v2 UUID contract
  changes.

## Local Verification

```bash
ruff format --check .
FLASK_DEBUG=1 pytest tests/contract tests/unit/test_migration_flags.py tests/unit/routes/test_migration_context_logging.py tests/unit/test_capture_migration_baseline.py tests/unit/libs/test_simulation_api_modal.py
make test
```

## Baseline Capture

Run against an explicitly chosen deployed URL:

```bash
API_BASE_URL=https://example-dot-policyengine-api.appspot.com \
python scripts/capture_migration_baseline.py --repetitions 5
```

To include the current simulation gateway completion baseline, provide a
representative economy-comparison payload:

```bash
API_BASE_URL=https://example-dot-policyengine-api.appspot.com \
SIMULATION_API_URL=https://policyengine--policyengine-simulation-gateway-web-app.modal.run \
SIMULATION_PAYLOAD_FILE=/path/to/representative-simulation-payload.json \
python scripts/capture_migration_baseline.py --repetitions 5
```

Record:

- request count
- status counts
- error rate
- p50 latency
- p95 latency
- simulation completion count
- simulation completion failures
- p50 completion time
- p95 completion time
- any probe errors

The script is opt-in. Normal CI must not depend on live deployed services.
