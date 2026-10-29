# Testing Skill

Use this skill whenever adding, moving, or reviewing tests.

## Test Environment

Tests run in the environment `uv.lock` defines, on Python 3.12, the same
versions the Cloud Run image installs (`gcp/cloud_run/Dockerfile`):

- `make install` runs `uv sync --frozen --extra dev`, and `make test` runs
  pytest and coverage through `uv run --frozen --extra dev`. The Makefile sets
  `UV_PYTHON=3.12` unless it is already set, because `.python-version` selects
  3.14.
- To run other commands in that environment, prefix them with
  `uv run --frozen --extra dev --python 3.12`. The commands below omit the
  prefix for brevity.
- A CI job that runs tests sets `UV_PYTHON: "3.12"`, installs with
  `make install` (or `uv sync --frozen --extra dev`), runs every pytest and
  coverage command through `uv run --frozen`, and never installs packages with
  pip. `tests/unit/test_locked_test_environments.py` checks the Python
  version and the Make targets; rules `api.dependencies.install-from-lock`
  and `api.dependencies.test-from-lock`
  ([dependencies.md](dependencies.md)) check every install and test command.

## Tests That Run a Country Model

A new unit test stands in for the country model: a calculation with the
installed policyengine-us takes seconds, and one of every variable takes most
of a minute. `tests/unit/test_country_spm.py` uses no `COUNTRIES["us"]`,
`load_forecast()` or real `Simulation`. It checks the country adapter's SPM
handling, and the household routes' SPM responses, over stand-in simulations
that raise the installed model's errors and report its receipts. Add a case
about what the API does with a model's SPM error or receipt there. Route cases
about storing, replaying and caching SPM selections, with a stand-in country,
are in `tests/unit/routes/test_canonical_spm.py`.

`tests/integration/test_installed_us_model_spm.py` holds two tests against
the installed US model: a chosen county returns a threshold and a receipt for
the pinned forecast, and a state-only household is null when it chose
nothing and a 400 when it chose a county. Which code the model raises for
each missing input is policyengine-us's to test. The file's fixtures build
the Flask app and its calculation service once per session. It needs no
database, network or credentials, so `make test` runs it after the unit
tests, in the pull request `Test` job and in the release tests.

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
FLASK_DEBUG=1 python -m pytest tests/unit/services/test_economy_service_budget_window_*.py -q
```

Regenerate and review `docs/engineering/migration-contracts.md` when
route inventory, migration registry flags, or v1 contract expectations change.
FastAPI shell-only fallback changes should not change the route catalog.

For Stage 6 native read routes, verify typed selection, Flask/native parity,
actual-route observability, contract preservation, and deployment checks
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
two independent connections, TTL expiry, atomic calculated-household results,
warnings and SPM receipts, bounded lookup indexes, completed-result miss
semantics, and token-safe coordination claims. Unit tests use the deterministic
in-memory fake and do not require network credentials.

Startup, deployment, SQLite-removal, and unchanged API migration contracts:

```bash
FLASK_DEBUG=1 uv run pytest tests/unit/v2/test_import_side_effects.py tests/unit/v2/test_report_v1_runtime_selection.py tests/unit/data/test_orm_sessions.py tests/unit/services/test_direct_orm_local_analysis.py tests/unit/test_app_engine_decommission.py tests/unit/test_cloud_run_deploy_scripts.py tests/unit/test_asgi_factory.py tests/contract/test_v1_route_contracts.py -q
python3 scripts/export_migration_contracts.py
python3 scripts/run_quality_guards.py
```

These checks must prove that imports, debug startup, ordinary startup, and
requests create no SQLite database or lock file; deployed startup launches no
Redis server; missing managed-cache configuration fails closed; Cloud SQL and
existing routes/compute remain primary; and generated migration-contract
artifacts remain current.

Cloud Run must receive `ROUTE_IMPL_HEALTH`, `ROUTE_IMPL_SPECIFICATION`,
`ROUTE_IMPL_METADATA`, `ROUTE_IMPL_POLICY`, `DB_READ_POLICY`, and
`DB_WRITE_POLICY` from the selected GitHub environment. Candidate resolution
must verify all six values on the exact revision. Staging promotion must wait
for the complete Cloud Run staging integration suite against the tagged
candidate. ASGI route tests must also prove that standard CORS middleware
answers browser preflight requests before route resolution and adds CORS
headers to error responses.

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

The platform-neutral release test suite must pass, with local Redis, before
GCP authentication, image publication, or candidate deployment. It runs in
`push.yml`'s `release-tests` job, which starts with the release run, beside the
checks and the staging database jobs; the Cloud Run staging deployment job
needs it, so none of its steps start until the tests pass. The job keeps the
`staging` environment and the variables the tests read when they ran inside
the deployment job, and has no GCP credentials.

Staging deployment checks run the live integration suite against the tagged
Cloud Run staging URL before promoting the exact tested revision to the
service URL. No production deployment may begin until the
staging integration, exact-revision promotion, and stable-URL health check
pass. Production Cloud Run promotion should happen only after tagged candidate
smoke tests pass. Both environments must capture
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

## Phase 10 Policy Migration

Run the configured static type check for the Phase 10 v2 query, route,
application-service, metadata-read, policy-create and read, and association
CRUD modules. The configured file set deliberately excludes the existing v1
implementation:

```bash
uv run --frozen --extra dev mypy
```

Run the shared query, SQLModel, native policy and association, v1 compatibility,
configuration, readiness, and observability tests together:

```bash
uv run pytest \
  tests/unit/test_query_parameters.py \
  tests/unit/v2/test_models.py \
  tests/unit/v2/test_model_persistence.py \
  tests/unit/v2/test_data_crud_boundaries.py \
  tests/unit/v2/test_policy_routes.py \
  tests/unit/v2/test_user_policy_routes.py \
  tests/unit/v2/test_user_policy_service.py \
  tests/unit/services/test_policy_service.py \
  tests/unit/services/test_user_policy_service.py \
  tests/unit/services/test_policy_mirroring.py \
  tests/unit/services/test_user_policy_mirroring.py \
  tests/unit/routes/test_policy_dual_write_routes.py \
  tests/unit/routes/test_user_policy_dual_write_routes.py \
  tests/unit/test_migration_flags.py \
  tests/unit/test_readiness.py \
  tests/contract -q
```

Use reviewed local MySQL and disposable PostgreSQL targets for the lifecycle,
persistence, and cross-database transaction tests. The v1 side of each
cross-database test must use MySQL rather than SQLite. Run these files
sequentially because they share the disposable databases; the lifecycle tests
prepare both schemas before the persistence tests:

```bash
ALEMBIC_DATABASE_URL="mysql+pymysql://.../policyengine_alembic_test" \
V2_ALEMBIC_DISPOSABLE_TEST=1 \
V2_MIGRATION_DATABASE_URL="postgresql+psycopg://.../policyengine_v2_alembic_test" \
uv run pytest \
  tests/integration/test_alembic_mysql_lifecycle.py \
  tests/integration/test_alembic_v2_lifecycle.py \
  tests/integration/test_v2_policy_persistence.py \
  tests/integration/test_v1_policy_dual_write.py \
  tests/integration/test_mysql_policy_dual_write.py \
  tests/integration/test_v2_user_policy_mirroring.py \
  tests/integration/test_v1_user_policy_dual_write.py -q
```

Continue to run the v1 compatibility suite because Phase 10 must also preserve
every v1 read and response contract:

```bash
uv run pytest \
  tests/contract/test_v1_route_contracts.py \
  tests/unit/services/test_policy_service.py \
  tests/unit/services/test_user_policy_service.py \
  tests/unit/routes/test_policy_dual_write_routes.py \
  tests/unit/routes/test_user_policy_dual_write_routes.py -q
```

Finally regenerate and validate migration contracts:

```bash
python scripts/export_migration_contracts.py
python scripts/run_quality_guards.py
uv run pytest tests/contract tests/unit/test_migration_contract_artifacts.py -q
```

## Stage 11 Household Migration

Run the configured static type check for the Stage 11 query, native HTTP,
application-service, persistence, translation, qualification, and association
modules:

```bash
uv run --frozen --extra dev mypy
```

Run the shared query, SQLModel, native household and association, v1
compatibility, source-selection, readiness, logging, import, and contract tests:

```bash
uv run --frozen pytest \
  tests/unit/test_query_parameters.py \
  tests/unit/v2/test_models.py \
  tests/unit/v2/test_household_models.py \
  tests/unit/v2/test_household_inputs.py \
  tests/unit/v2/test_household_canonicalization.py \
  tests/unit/v2/test_household_translation.py \
  tests/unit/v2/test_household_query.py \
  tests/unit/v2/test_household_persistence_statements.py \
  tests/unit/v2/test_household_routes.py \
  tests/unit/v2/test_user_household_service.py \
  tests/unit/v2/test_user_household_routes.py \
  tests/unit/v2/test_household_migration_qualification.py \
  tests/unit/services/test_household_service.py \
  tests/unit/services/test_household_mirroring.py \
  tests/unit/routes/test_household_dual_write_routes.py \
  tests/unit/routes/test_migration_context_logging.py \
  tests/unit/test_household_event_command.py \
  tests/unit/test_migration_flags.py \
  tests/unit/test_readiness.py \
  tests/unit/v2/test_import_side_effects.py \
  tests/contract -q
```

Use only reviewed disposable databases for both schema lifecycles and the
PostgreSQL and cross-database transaction tests:

```bash
ALEMBIC_DATABASE_URL="mysql+pymysql://.../policyengine_alembic_test" \
V2_ALEMBIC_DISPOSABLE_TEST=1 \
V2_MIGRATION_DATABASE_URL="postgresql+psycopg://.../policyengine_v2_alembic_test" \
uv run --frozen pytest \
  tests/integration/test_alembic_mysql_lifecycle.py \
  tests/integration/test_alembic_v2_lifecycle.py \
  tests/integration/test_v2_household_persistence.py \
  tests/integration/test_v1_household_dual_write.py \
  tests/integration/test_mysql_household_spm_dual_write.py -q
```

Regenerate migration contracts, run repository checks, and confirm the
generated files match their registries:

```bash
python scripts/export_migration_contracts.py
python scripts/run_quality_guards.py
uv run --frozen pytest \
  tests/contract \
  tests/unit/test_migration_contract_artifacts.py \
  tests/unit/test_cloud_run_deploy_scripts.py \
  tests/unit/v2/test_metadata_deployment.py -q
```

## Stage 12A User Login and Associations

Run the static type check, then the user route, service, authentication,
contract, and deployment tests:

```bash
uv run --frozen --extra dev mypy
uv run --frozen pytest \
  tests/unit/libs/test_user_auth.py \
  tests/unit/libs/test_auth0_management.py \
  tests/unit/v2/test_user_route_auth.py \
  tests/unit/v2/test_me_routes.py \
  tests/unit/v2/test_user_policy_routes.py \
  tests/unit/v2/test_user_household_routes.py \
  tests/unit/v2/test_user_simulation_report_routes.py \
  tests/unit/v2/test_user_policy_service.py \
  tests/unit/v2/test_user_household_service.py \
  tests/unit/v2/test_user_account_service.py \
  tests/unit/v2/test_unauthenticated_user_service.py \
  tests/unit/v2/test_legacy_reference_service.py \
  tests/unit/v2/test_user_association_migration_qualification.py \
  tests/unit/v2/test_models.py \
  tests/unit/v2/test_alembic_v2.py \
  tests/unit/test_readiness.py \
  tests/unit/test_cloud_run_deploy_scripts.py \
  tests/unit/test_migration_contract_artifacts.py \
  tests/contract -q
```

Prove provisioning races (signed-in and signed-out), conversion and merge at
sign-in under concurrency, the row locks that keep a signed-out browser from
acting on its converted user, named conflict targets, and the reshape
lifecycle against the disposable Postgres database:

```bash
V2_ALEMBIC_DISPOSABLE_TEST=1 \
V2_MIGRATION_DATABASE_URL="postgresql+psycopg://.../policyengine_v2_alembic_test" \
uv run --frozen pytest \
  tests/integration/test_alembic_v2_lifecycle.py \
  tests/integration/test_v2_user_identity_persistence.py -q
```

Route tests inject a principal (a `UserPrincipal` or an
`UnauthenticatedPrincipal`) through `NativeRouteDependencies(require_user=...)`;
omit it to exercise the fail-closed default authenticator.
`tests/integration/test_live_v2_policies.py` is a staging deploy gate that
signs in the staging Auth0 test user and saves work as fresh signed-out
browsers; it is not run locally.
