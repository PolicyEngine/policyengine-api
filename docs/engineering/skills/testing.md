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

Regenerate and review `docs/engineering/migration-contracts.md` when
route inventory, migration registry flags, or v1 contract expectations change.
FastAPI shell-only fallback changes should not change the route catalog.

For Stage 6 native read routes, verify typed selection, Flask/native parity,
actual-route observability, contract preservation, and deployment gates
together:

```bash
python scripts/export_migration_contracts.py
python scripts/run_quality_guards.py
FLASK_DEBUG=1 python -m pytest tests/unit/test_migration_flags.py tests/unit/test_asgi_factory.py tests/unit/test_stage6_native_metadata.py tests/unit/routes/test_migration_context_logging.py tests/unit/services/test_metadata_service.py tests/contract/test_v1_route_contracts.py -q
python -m pytest tests/unit/test_cloud_run_deploy_scripts.py tests/unit/test_capture_migration_baseline.py tests/unit/test_compare_migration_baseline.py -q
```

For v2 platform foundation work, run the smallest applicable group while
iterating, then all groups before qualification.

SQLModel schema, report/run behavior, lazy configuration, and import effects:

```bash
uv run pytest tests/unit/v2/test_models.py tests/unit/v2/test_model_persistence.py tests/unit/v2/test_report_runs.py tests/unit/v2/test_settings.py tests/unit/v2/test_import_side_effects.py -q
```

The generated-only v2 Alembic chain and disposable Postgres lifecycle:

```bash
uv run pytest tests/unit/v2/test_alembic_v2.py tests/unit/test_alembic_workflows.py -q
V2_ALEMBIC_DISPOSABLE_TEST=1 V2_MIGRATION_DATABASE_URL="postgresql+psycopg://.../policyengine_v2_alembic_test" \
  uv run pytest tests/integration/test_alembic_v2_lifecycle.py -q
```

The disposable lifecycle must start from empty Postgres, upgrade to `head`,
check schema drift, compare the live schema directly with the authoritative
SQLModel metadata, downgrade the compact baseline to `base`, verify its native
Postgres enum types are removed, and upgrade again. It
must not use the persistent Supabase qualification bypass outside explicit
disposable-test mode. Continue running the existing isolated v1 MySQL
lifecycle whenever either Alembic domain changes.

Shared-cache unit behavior and real Redis-compatible integration semantics:

```bash
uv run pytest tests/unit/runtime_cache tests/unit/services/test_household_calculation_service.py tests/unit/services/test_reform_impacts_service.py tests/unit/services/test_budget_window_cache.py -q
RUNTIME_CACHE_TEST_URL="redis://127.0.0.1:6379/0" uv run pytest tests/integration/test_runtime_cache_redis.py -q
```

The real Redis-compatible suite must be an explicit integration run and cover
two independent connections, TTL expiry, atomic household/tracer generations,
bounded lookup indexes, completed-result miss semantics, and token-safe
coordination claims. Unit tests use the deterministic in-memory fake and do
not require network credentials.

Startup, deployment, SQLite-removal, and unchanged API migration contracts:

```bash
FLASK_DEBUG=1 uv run pytest tests/unit/v2/test_import_side_effects.py tests/unit/v2/test_report_v1_runtime_selection.py tests/unit/data/test_orm_sessions.py tests/unit/services/test_direct_orm_local_analysis.py tests/unit/test_app_engine_runtime.py tests/unit/test_cloud_run_deploy_scripts.py tests/unit/test_asgi_factory.py tests/contract/test_v1_route_contracts.py -q
python3 scripts/export_migration_contracts.py
python3 scripts/run_quality_guards.py
```

These checks must prove that imports, debug startup, ordinary startup, and
requests create no SQLite database or lock file; deployed startup launches no
Redis server; missing managed-cache configuration fails closed; Cloud SQL and
existing routes/compute remain primary; and generated migration-contract
artifacts remain current.

Cloud Run must receive `ROUTE_IMPL_HEALTH`, `ROUTE_IMPL_SPECIFICATION`, and
`ROUTE_IMPL_METADATA` from the selected GitHub environment. Candidate
resolution must verify those values on the exact revision. Staging promotion
must wait for the complete Cloud Run staging integration suite against the
tagged candidate.

For PR 3 Cloud Run candidate deployment changes, verify the command-building
guards, workflow track structure, ASGI compatibility, and container build:

```bash
python -m pytest tests/unit/test_cloud_run_deploy_scripts.py tests/unit/test_asgi_factory.py -q
docker build -f gcp/cloud_run/Dockerfile -t policyengine-api-cloud-run:test .
```

If the Cloud Run container startup script changes, keep the script syntax and
child-process supervision assertions in `tests/unit/test_cloud_run_deploy_scripts.py`
updated. The tests must assert that only the API server is supervised, no
container-local Redis process is launched, and deployed configuration selects
managed Redis without a localhost fallback.

Staging deployment checks should run the same live integration suite against
both the App Engine staging URL and the tagged Cloud Run staging URL before
promoting the exact tested Cloud Run revision to the service URL. No production
deployment may begin until the staging integrations, exact-revision promotion,
and stable-URL health check pass. Production Cloud Run promotion should happen
only after tagged candidate smoke tests pass. Both environments must capture
the previously serving revision, guard against concurrent traffic changes,
re-resolve the tested tag to require the same exact revision and immutable
image, promote with `--to-revisions`, health-check the stable URL, and
automatically restore the captured revision if promotion or stable verification
fails. Live Cloud Run candidate checks must be explicit deployed probes.
Production candidate smoke tests require `API_BASE_URL` and should not run as
part of ordinary local test commands. These checks should stay read-only and
avoid depending on specific production data fixtures:

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
