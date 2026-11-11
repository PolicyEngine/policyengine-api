# Testing Skill

Use this skill whenever adding, moving, or reviewing tests.

## Test Environment

Tests run in the environment `uv.lock` defines, on Python 3.12, the same
versions the Cloud Run image installs (`gcp/cloud_run/Dockerfile`):

- `make install` turns on the git hooks in `.githooks` and runs
  `uv sync --frozen --extra dev`, and `make test` runs
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

## Every Test Checks Something

`api.quality.tests-assert`: every test function checks its outcome. A test
that checks nothing passes whatever the code returns, as long as nothing
raises. The `asserting-tests` quality guard
(`scripts/rules/asserting_tests.py`) reads every tracked `test_*.py` and
`*_test.py` file, apart from the rules' proof fixtures under `rules/fixtures/`
and `scripts/rules/tests/fixtures/`. It finds the tests pytest and unittest
collect, and fails on a test whose body contains none of:

- an `assert` statement, or `raise AssertionError`;
- `pytest.raises`, `pytest.warns`, `pytest.deprecated_call` or `pytest.fail`,
  also through `import pytest as pt` or `from pytest import raises`;
- a call to a function or method whose name starts with `assert` or
  `_assert`, such as `self.assertEqual`, a mock's `assert_called_once_with`
  or `assert_frame_equal` (also imported under another name), or unittest's
  `self.fail`;
- a call to a test helper that does one of these, followed through further
  helpers: a function of the same file called by name, a method of the
  test's own class called through `self`, `cls` or `super()` (looked up in
  Python's method resolution order), or a function
  imported by name (`from tests.unit.support import check_response`, at the
  top of the file or inside the test, also through a re-export or a star
  import) from test code: a module under a `tests` directory, a test file or
  a `conftest.py`.

Only the test's body counts, not its decorators or default arguments. A
function, class or lambda assigned to a name in the body counts only when the
body refers to it by name: a stand-in that raises `AssertionError` when the
code calls it is a check once the test passes it to the code. `self` in a
stand-in class's methods is the stand-in, not the test's class. Production
code isn't a helper, even if it raises on bad input. A name resolves from
the call's own scope outward, as in Python: a parameter (such as a fixture
called like a function), a local variable, a lambda or comprehension
variable, or an import inside the test hides a module-level helper of the
same name, but a name bound only in a nested function doesn't.

The guard collects tests as pytest does, for what it can read without
importing anything:

- module-level `test*` functions, also inside `if`, `try` and `with` blocks,
  except pytest fixtures;
- `test*` methods of `Test*` classes that have no `__init__` or `__new__` and
  aren't dataclasses, including methods and nested `Test*` classes inherited
  from bases in test code;
- methods of `unittest.TestCase` subclasses;
- test functions and classes imported into a test module, by name or with a
  star import, under the name the import binds.

Methods are looked up as Python looks them up, including those in `if`
blocks of a class body; a later definition replaces an earlier one, and an
attribute such as `test_inherited = None` switches an inherited test off.
The nearest `__test__` setting on a module or class decides whether it is
collected, as for pytest: `False` switches a class off, and `True` collects
a class whatever its name. `scripts/rules/tests/` runs under
`unittest discover`, which collects only `TestCase` subclasses and ignores
`__test__`. A base class outside test code isn't read, so an `__init__`
there isn't seen.

A test that only shows that a call doesn't raise checks nothing: assert what
the call returns or what it changes instead. A helper reached any other way
(`support.check(...)` after `import tests.unit.support as support`, or a
method of another object) isn't followed, so name it `assert_...` or import
it by name.

The rule is ratcheted. `rules/baselines/tests-without-checks.txt` lists the
21 tests that checked nothing when the rule was added, as `<path>::<test>`
(`<test>` is `Class::method` for a method). A test not listed there fails,
and a listed one that is gone or now checks something fails as stale: remove
its line and lower the rule's baseline `count`. Renaming or moving a listed
test also fails, because its new entry is one the base branch's baseline
lacks, so give it a check in the same change.

## Coverage

`api.quality.coverage-measured`: Codecov measures the same tests on `master`
as on pull requests, so a pull request's project coverage is compared with a
base that measured them too. `codecov.yml` defines two flags, both carried
forward and both covering `policyengine_api/` (`.coveragerc`'s source):

- `unit`: `make test`. On a pull request, the six `Test` shards keep their
  `coverage.xml`, and `upload-test-coverage` in `pr.yml` sends them to
  Codecov in one upload. On `master`, `push.yml`'s `release-tests` shards do
  the same on each release commit, and `upload-release-test-coverage` sends
  them; it is the only run of the unit tests on the merged code.
- `integration`: the cross-database integration tests in
  `v2-integration-check.yml`. The reusable workflow keeps its report as an
  artifact, and `upload-integration-coverage` in `pr.yml` and in `push.yml`
  sends it, wherever those tests run.

A commit that uploads one flag carries the other forward from its Codecov
parent, a git parent that has a Codecov report. When both of a merge
commit's parents have one, which Codecov takes isn't fixed. On `master`:

- the merge run uploads `integration` for the merge commit, which carries
  `unit` forward from the pull request head or from the `master` commit before
  it until the release run;
- the release run uploads the release tests' `unit` coverage for the release
  commit, which carries `integration` forward from the merge commit, and also
  for the merge commit (`override_commit`): `versioning`'s release commit
  changes only the version, `uv.lock` and the changelog, so the release tests
  measure the merge commit's code too.

Codecov compares a pull request with the `master` commit it branched from or
last merged in. For 40 recently merged pull requests that was a release
commit for 21 and a merge commit for 17, since a merge commit is `master`'s
tip until its release commit lands, and a lower stacked pull request's
commit for 2. A release commit, and a merge commit followed by its own
release commit (7 of the 17), measured both flags on their own code. The
other merge commits never got a release commit: `versioning`'s push fails
when `master` moves during the merge run, and the next release covers both
merges. Their `unit` coverage stays carried forward from an earlier commit.
Codecov also recomputes a pull request's comparison only when the pull
request gets an upload, so one compared before its base's `unit` upload shows
the carried-forward figure until its next push.

The release tests run in the `staging` environment, with its variables
(`SIM_ENTRYPOINT`, `SIMULATION_ENTRYPOINT_URL`,
`POLICYENGINE_DB_INSTANCE_CONNECTION_NAME`,
`PRODUCTION_CLOUD_RUN_POLICYENGINE_DB_PASSWORD_SECRET`, the
`GATEWAY_AUTH_*` secrets) and the local Redis runtime cache, and without GCP
credentials. The pull request `Test` job authenticates to GCP and sets none
of those. Code that branches on them is covered differently in the two, so
`master`'s unit figure and a pull request's can differ by those lines even for
the same code.

Every upload passes the `CODECOV_TOKEN` repository secret as its `token` and
runs in a job with a timeout of at most 15 minutes, since the Codecov action
sets no network timeouts. An upload on `master` fails the run when it fails
(`fail_ci_if_error`), and no job in a `master` run waits for an upload, so a
Codecov outage fails the upload job but can't stop a release. On a pull
request, `CI complete` needs the upload jobs, which don't fail on an upload
error. `tests/unit/test_codecov_coverage.py` checks the uploads and
`codecov.yml`: a new job that measures coverage needs an upload of every
shard of its report, flagged `unit` for the test suite and `integration`
otherwise.

The project status allows a 0.5% drop. The patch status reports coverage of
the changed lines without blocking a merge.

### Changed lines

`api.quality.diff-coverage`: at least 80% of the lines a pull request changes
in `policyengine_api/` that coverage.py measures run in the unit or
integration tests. The `diff-coverage` job in `pr.yml` runs after the `Test`
shards and the integration tests. It downloads every shard's `coverage.xml`
and the integration tests' `coverage-v2.xml`, and runs
`diff-cover --fail-under=80` against `HEAD^1`. CI checks out the merge commit
GitHub builds for the pull request, so `HEAD^1` is the commit that merge is
built on: the base branch, or for a pull request stacked on another, the
lower one's merge commit (the job runs only on the lowest pull request of a
stack). Either way the diff holds only the pull request's changes. The
event's `base.sha` isn't used: it can stay where the branch left `master`,
which would count `master`'s later changes as the pull request's. A line
counts as covered if any report covers it. `CI complete` needs the job, so a
pull request below the minimum can't merge. The job's log lists each changed
file's uncovered lines.

Only measured files count, so a pull request that changes no code under
`policyengine_api/` passes. coverage.py measures every module there, whether
or not a test imports it, but only inside a package: every directory under
`policyengine_api/` needs an `__init__.py`, or its untested modules are left
out and their changed lines pass.
`tests/unit/test_diff_coverage.py::test_coverage_reports_every_module_no_test_imports`
fails for a directory without one. Lines that never run by design don't
count (`.coveragerc`): imports under `if TYPE_CHECKING:`, `...` alone on a
line (the bodies of Protocol methods and other stubs), and lines marked
`# pragma: no cover`.

What counts as a line is coverage.py's: the first line of each statement.
Changing the second or a later line of a statement that spans several lines
adds nothing to the count, and a line that ran counts as covered even if one
of its branches never ran. Only the `Test` shards and the tests in
`v2-integration-check.yml` are measured: code that runs only in the Alembic
checks, the environment-variable tests, `push.yml`'s live tests or a
subprocess a test starts counts as uncovered. Moving code into a new file
counts its lines as changed, so splitting a module that tests cover poorly
needs tests for the moved code. git's rename detection is the exception: a
new file at least 50% similar to a file the pull request deletes is paired
with it, and only its edited lines count.

Codecov's patch status shows an 80% target too, but doesn't block a merge,
and its figure can differ: it compares with the `master` commit the branch
left from or last merged in, and counts a line with a branch that never ran
as not covered.

To check before pushing, delete `.coverage` (`make test` adds to it), run
`make test`, which writes `coverage.xml`, and then:

```bash
uv run --frozen --extra dev --python 3.12 diff-cover coverage.xml --compare-branch=origin/master --fail-under=80
```

That leaves out the integration tests, which need the databases
`v2-integration-check.yml` starts, so CI's figure can be higher.

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
  uv run pytest tests/integration/test_alembic_v2_lifecycle.py tests/integration/test_alembic_v2_catalog_tables.py -q
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

The release test suite runs in six shards, one runner each, so that it
finishes before the staging database jobs do. `run_release_tests.sh` loads the
pytest plugin `tests/release_test_shard_plugin.py`: every runner collects the
whole suite and keeps the tests in the files `scripts/release_test_shards.py`
assigns to its shard, heaviest file first, by the measured seconds in
`MEASURED_FILE_SECONDS` or else by test count. A file's tests stay in one
shard, so its fixtures are set up once. The `check-release-test-shards` job
then fails, and the staging deployment with it, unless every shard collected
the same tests and each test ran in exactly one shard. The plugin reads its
settings once, when pytest configures it, and then removes them and its `-p`
option from `PYTEST_ADDOPTS`, so a pytest process that a test starts collects
its own tests without the split; a shard writes its report once, and fails if
one is already there. When a test file becomes much slower or faster, measure
it again with `--durations=0` and update `MEASURED_FILE_SECONDS`; an
out-of-date value only makes the shards finish less evenly.

Every pull request runs the same six shards in `pr.yml`'s `test` job, which
runs `make test` with the plugin in `PYTEST_ADDOPTS`, as
`run_release_tests.sh` does, and its `check-test-shards` job runs the same
check, so a change that breaks the split fails before it merges. Each shard
keeps its `coverage.xml` as an artifact, and the `upload-test-coverage` job
sends all six to Codecov in one upload: with an upload from each shard, Codecov
updated its checks after every upload and could leave one in progress. "CI
complete" needs all three jobs.

The release run skips lint, the quality guards, both Alembic checks and the
cross-database integration tests when its merge run passed them on the same
code: `check-release-commit` (`.github/release_commit.py`) requires that the
release commit changes only the `[project]` version in `pyproject.toml`, the
project's own version entry in `uv.lock`, `CHANGELOG.md` and removed changelog
fragments, and that the merge commit's Push run passed all five checks.
Otherwise the release run runs them, and `publish-git-tag` requires lint, both
Alembic checks and the integration tests to pass, as before. The release test
suite always runs.

CI never loads the complete installed PolicyEngine.py catalog (about 1.2
million parameter values). Two tests in the cross-database check cover
publishing it instead, on every run:

- `test_v2_catalog_installed_folders.py` runs the real US and UK models through
  extraction and publication, reduced to the parameter folders in its
  `SELECTED_FOLDERS`, and reads every value back. Between them the folders
  hold every value shape the installed models hold, and the test fails when
  one is missing: replace a renamed folder with one that holds the same
  values.
- `test_v2_catalog_publication.py` publishes
  `tests/fixtures/v2_catalog_value_shapes.py`, which holds one example of each
  value shape extraction accepts, and reads every value back. When extraction
  accepts a new shape, add an example there.

Each release publishes and validates the complete catalog against staging,
then production, in `seed-v2-database.yml`.

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
avoid depending on specific production data fixtures. The deployed-API tests
send the CI server credential from `CI_SERVER_ACCESS_TOKEN` through the
`api_client` fixture, and fail without it: a client-credentials token of a
client on that environment's `PUBLIC_API_SERVER_CLIENT_IDS`
(`tests/integration/deployed_api_credentials.py`). Only refusal checks use
`uncredentialed_api_client`, which sends no credential. In push.yml each job that
sets `API_BASE_URL` requests one with
`.github/scripts/request_ci_server_token.sh`, and
`tests/unit/test_ci_server_credential_workflow.py` fails for a job that
doesn't:

```bash
API_BASE_URL=https://candidate-url CI_SERVER_ACCESS_TOKEN=... python -m pytest tests/integration/test_cloud_run_candidate.py -v
```

Before committing AI-authored code changes, run the quality checks, as
"Commit Hygiene" in the GitHub PRs skill describes:

```bash
make quality
```

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
  tests/integration/test_alembic_v2_catalog_tables.py \
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
  tests/unit/routes/test_policy_dual_write_routes.py -q
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
  tests/integration/test_alembic_v2_catalog_tables.py \
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
  tests/unit/v2/test_user_types.py \
  tests/unit/v2/test_user_type_service.py \
  tests/unit/v2/test_admin_user_routes.py \
  tests/unit/test_set_v2_user_type_script.py \
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
  tests/integration/test_alembic_v2_catalog_tables.py \
  tests/integration/test_v2_user_identity_persistence.py \
  tests/integration/test_v2_user_type_persistence.py -q
```

Route tests inject a principal (a `UserPrincipal` or an
`UnauthenticatedPrincipal`) through `NativeRouteDependencies(require_user=...)`;
omit it to exercise the fail-closed default authenticator.
`tests/integration/test_live_v2_policies.py` is a staging deploy gate that
signs in the staging Auth0 test user and saves work as fresh signed-out
browsers; it is not run locally.
