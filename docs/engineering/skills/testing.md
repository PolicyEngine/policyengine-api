# Testing Skill

Use this skill whenever adding, moving, or reviewing tests.

## Migration Test Layout

- Put API migration compatibility tests under `tests/contract/`.
- Put focused unit tests for migration flags, generated artifacts, guard
  scripts, or baseline tools under `tests/unit/`.
- Keep contract tests isolated from live Cloud SQL, Modal, external AI APIs, and
  network credentials unless the test is explicitly marked as a live integration
  probe.

## Focused Commands

For PR 1 migration harness changes, prefer these focused checks before running
the full suite:

```bash
python scripts/run_quality_guards.py
python scripts/export_migration_contracts.py
python -m pytest tests/contract tests/unit/test_migration_flags.py tests/unit/test_migration_contract_artifacts.py tests/unit/test_capture_migration_baseline.py tests/unit/routes/test_migration_context_logging.py -q
```

For PR 2 FastAPI shell or Flask fallback changes, verify the ASGI entrypoint and
the v1 route contracts together:

```bash
FLASK_DEBUG=1 python -m pytest tests/unit/test_asgi_factory.py tests/contract/test_v1_route_contracts.py tests/unit/routes/test_migration_context_logging.py -q
```

If the change touches service compatibility behavior used by migrated or
candidate endpoints, add the relevant focused service tests. For budget-window
simulation compatibility, run:

```bash
FLASK_DEBUG=1 python -m pytest tests/unit/services/test_economy_service.py::TestEconomyService::TestGetBudgetWindowEconomicImpact -q
```

Regenerate and review `docs/engineering/generated/migration_contracts.md` when
route inventory, migration registry flags, or v1 contract expectations change.
FastAPI shell-only fallback changes should not change the route catalog.

For PR 3 Cloud Run candidate deployment changes, verify the command-building
guards, workflow track structure, ASGI compatibility, and container build:

```bash
python -m pytest tests/unit/test_cloud_run_deploy_scripts.py tests/unit/test_asgi_factory.py -q
docker build -f gcp/cloud_run/Dockerfile -t policyengine-api-cloud-run:test .
```

If the Cloud Run container startup script changes, keep the script syntax and
child-process supervision assertions in `tests/unit/test_cloud_run_deploy_scripts.py`
updated. The tier 1 Redis path keeps Redis local to the container, so tests
should verify the bash entrypoint, explicit Redis/Uvicorn PID tracking, and
fail-fast behavior rather than any managed Redis integration.

Staging deployment checks should run the same live integration suite against
both the App Engine staging URL and the tagged Cloud Run staging URL before
promoting the tested Cloud Run tag to the service URL. App Engine production
candidate deploys may run before the staging integration jobs finish, but must
use `APP_ENGINE_PROMOTE=0`; the traffic promotion job must remain gated on the
staging checks and production model-version alignment. Production Cloud Run
promotion should happen only after tagged candidate smoke tests pass, and should
health-check the Cloud Run service URL after promotion. Live Cloud Run candidate
checks must be explicit deployed probes. Production candidate smoke tests
require `API_BASE_URL` and should not run as part of ordinary local test
commands. These checks should stay read-only and avoid depending on specific
production data fixtures:

```bash
API_BASE_URL=https://candidate-url python -m pytest tests/integration/test_cloud_run_candidate.py -v
```

Before committing AI-authored code changes, run repository formatting and lint:

```bash
make format
ruff check <changed Python files>
```

Commit only after formatting succeeds and changed Python files pass lint. If a
broader repo-wide lint command fails on unrelated pre-existing issues, include
that result in the handoff instead of hiding it.
