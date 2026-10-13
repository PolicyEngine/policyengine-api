# Agent Instructions

These instructions apply repository-wide.

## Skills System

Canonical AI-facing engineering skills live under `docs/engineering/skills/`.
Use those files as the source of truth across Codex, Claude, Copilot, and other
AI tools.

When adding an HTTP route or changing an existing route's query-parameter
contract, read `docs/engineering/skills/api-routes.md`.

When changing API v2 migration contracts, route-group migration metadata, PR
cutover plans, generated migration docs, or migration guard scripts, read
`docs/engineering/skills/migration_contracts.md`.

When adding, moving, or reviewing tests, read
`docs/engineering/skills/testing.md`.

When changing SQLAlchemy models, Alembic configuration, database schemas, or
migration revisions, read
`docs/engineering/skills/alembic-migrations.md`.

When adding or moving API v2 route, service, or database-access modules, read
`docs/engineering/skills/v2-code-organization.md`.

When changing correlation identifiers, telemetry transport, spans, stage
names, logging, or observability failure handling, read
`docs/engineering/skills/observability.md`.

When modifying the `Makefile`, read
`docs/engineering/skills/repository-maintenance.md`.

When adding or changing a GitHub Actions workflow step or a script under
`.github/scripts/`, read `docs/engineering/skills/ci-workflows.md`.

When adding, changing, or removing a rule, a guard test, a checker
configuration, or a CI job that enforces one, read
`docs/engineering/skills/rules-registry.md`.

## GitHub PRs

Read `docs/engineering/skills/github-prs.md` before opening, replacing, or
sharing any pull request. Every PR needs a tracking issue and
`Fixes #ISSUE_NUMBER` as the first line of its description. Agents must never
bypass branch rules (for example with `gh pr merge --admin`).

Before creating or sharing a migration PR, run the focused migration guards:

```bash
python scripts/run_quality_guards.py
python scripts/export_migration_contracts.py
```

## Safety Boundaries

Do not claim a route, database table, compute path, or deployment surface has
migrated unless the relevant contract tests, migration flags, and generated
migration docs identify that state.

## Rules

<!-- BEGIN GENERATED: rules (python -m scripts.rules render) -->

Every rule for this repository lives in `rules/registry.toml` and is rendered,
with its enforcement and gaps, in `docs/generated/rules.md`. Blocking rules
fail CI. Doc-only rules are not checked automatically, so follow them yourself.
To add or change a rule, read `docs/engineering/skills/rules-registry.md`.

### API v2 layer boundaries

- `api.routes.shared-query-parameters`: Routes that accept query parameters define them through the shared typed query models, never with a second manual parser. (doc-only, not checked: follow it yourself)
- `api.v2.connectors-mutations-no-reads`: v2 mutation connectors (creates, updates, deletes) never issue select or get reads. (blocking: pytest `tests/unit/v2/test_data_crud_boundaries.py`)
- `api.v2.connectors-never-commit`: v2 connectors receive a session from the service and never open, commit, roll back or close it. (doc-only, not checked: follow it yourself)
- `api.v2.connectors-no-cross-calls`: v2 connector modules never call one another to sequence a workflow; the service does the sequencing. (doc-only, not checked: follow it yourself)
- `api.v2.connectors-reads-no-mutations`: v2 read connectors never insert, add or delete rows. (blocking: pytest `tests/unit/v2/test_data_crud_boundaries.py`)
- `api.v2.crud-checks-cover-every-resource`: The v2 CRUD boundary checks find modules by filename, so every resource package is covered, and every connector module is named as a create, read, update or delete module. (blocking: pytest `tests/unit/v2/test_data_crud_boundaries.py`)
- `api.v2.routes-no-sessions-or-sql`: v2 route modules never open database sessions or construct SQL; they call one service method and map typed failures to HTTP. (doc-only, not checked: follow it yourself)
- `api.v2.services-no-sql`: v2 services sequence work but never construct SQL expressions, call Session.exec, or define HTTP response models. (doc-only, not checked: follow it yourself)
- `api.v2.session-modules-no-queries`: v2 database_session modules own session lifetime only and never build select, insert, update, delete or exec calls. (blocking: pytest `tests/unit/v2/test_data_crud_boundaries.py`)
- `api.v2.user-services-no-sql`: v2 user services (identity, accounts, legacy references and user associations) never build or run SQL themselves or import SQLAlchemy; their connectors do. (blocking: pytest `tests/unit/v2/test_data_crud_boundaries.py`)
- `api.v2.validators-transformations-no-db`: v2 validators and transformations never import SQLAlchemy or SQLModel query or session APIs. (blocking: pytest `tests/unit/v2/test_data_crud_boundaries.py`)

### Runtime persistence and route boundaries

- `api.data.runtime-sql-confined`: Raw SQL is confined to the data-access layer; runtime modules and report orchestration use sessions and mapped models. (blocking: pytest `tests/unit/data/test_runtime_sql_boundaries.py`)
- `api.legacy.removed-layers-stay-removed`: Removed legacy persistence layers, the temporary DAO module and the legacy endpoints package stay removed. (blocking: pytest `tests/unit/data/test_runtime_sql_boundaries.py`, `tests/unit/routes/test_flask_route_boundaries.py`, `tests/unit/services/test_orm_service_boundaries.py`)
- `api.routes.flask-blueprints-own-urls`: Legacy Flask URLs are owned by blueprints, and the Flask app assembles blueprints without legacy endpoint wiring. (blocking: pytest `tests/unit/routes/test_flask_route_boundaries.py`)
- `api.routes.no-domain-logic-in-http`: Flask routes delegate domain processing (economy comparison, calculation) to services instead of doing it in the HTTP layer. (blocking: pytest `tests/unit/routes/test_flask_route_boundaries.py`)
- `api.routes.no-inline-json-errors`: Flask routes never build JSON error responses inline; they use the shared error handling. (blocking: pytest `tests/unit/routes/test_flask_route_boundaries.py`)
- `api.services.no-direct-queries`: Services never issue database queries or open database connections directly; they delegate persistence to the data-access layer. (blocking: pytest `tests/unit/services/test_local_data_service_boundaries.py`, `tests/unit/services/test_orchestration_service_database_boundaries.py`, `tests/unit/services/test_orm_service_boundaries.py`, `tests/unit/services/test_run_and_spec_service_database_boundaries.py`)
- `api.services.session-ownership`: Migrated services use sessions and mapped models; their public methods never accept persistence objects, and routes and the economy service never manage sessions. (blocking: pytest `tests/unit/services/test_local_data_service_boundaries.py`, `tests/unit/services/test_orm_service_boundaries.py`)

### Import and startup side effects

- `api.catalog.initializer-not-at-startup`: Application startup modules never import the metadata catalog initializer. (blocking: pytest `tests/unit/v2/test_catalog_initialization.py`)
- `api.startup.fail-closed-configuration`: Default Cloud SQL startup needs no Supabase configuration, and a selected v2 runtime without its database URL fails closed. (blocking: pytest `tests/unit/v2/test_import_side_effects.py`)
- `api.startup.no-import-side-effects`: Importing v2 modules, starting up and serving a request open no network connections and create no files or runtime SQLite databases. (blocking: pytest `tests/unit/v2/test_import_side_effects.py`)
- `api.startup.no-runtime-sqlite-modules`: Runtime SQLite modules are absent from the production package. (blocking: pytest `tests/unit/v2/test_import_side_effects.py`)

### Data source isolation

- `api.catalog.extractor-import-isolation`: The catalog extractor never imports PolicyEngine core, country packages or v1 metadata directly. (blocking: pytest `tests/unit/v2/test_catalog_extraction.py`)
- `api.metadata.read-modules-isolated`: v2 metadata read modules never import PolicyEngine packages or v1 metadata sources. (blocking: pytest `tests/unit/v2/test_metadata_service.py`)
- `api.reports.v1-persistence-only`: The existing report route and service import only v1 persistence. (blocking: pytest `tests/unit/v2/test_report_v1_runtime_selection.py`)
- `api.stage12.comparison-tables-isolated`: Serving routes and services never read the Stage 12 comparison tables, and production tables never depend on them. (blocking: pytest `tests/unit/v2/test_stage12_comparison_isolation.py`)
- `api.stage12.retirement-owned`: Retiring the Stage 12 comparison schema stays owned by a named follow-up change in the Stage 12 worker contract. (blocking: pytest `tests/unit/v2/test_stage12_comparison_isolation.py`)
- `api.v2.single-orm-layer`: v2 models never create a parallel SQLAlchemy ORM layer alongside SQLModel. (blocking: pytest `tests/unit/v2/test_model_persistence.py`)

### Migration and schema

- `api.migration.alembic-autogenerated-only`: Alembic revisions are autogenerated against an explicitly selected v1 or v2 configuration; never hand-written DDL or data operations. (doc-only, not checked: follow it yourself)
- `api.migration.alembic-v1-qualified`: v1 Alembic revisions qualify against a disposable MySQL database. (blocking: CI job `alembic-v1-check`)
- `api.migration.alembic-v2-qualified`: v2 Alembic revisions qualify against a disposable Postgres database, and alembic check finds no schema drift. (blocking: CI job `alembic-v2-check`)
- `api.migration.bundle-supported-by-simulation-api`: A PolicyEngine bundle version change is supported by the simulation API before it merges. (blocking: CI job `ensure-policyengine-bundle-supported-by-simulation-api`)
- `api.migration.contracts-consistent`: Migration route groups and workflow contracts are internally consistent, and their generated docs are current. (blocking: quality guard `migration-contracts`)
- `api.migration.cross-database-integration`: Cross-database integration tests pass against real MySQL and Postgres. (blocking: CI job `v2-integration-check`)

### Code quality and types

- `api.quality.alembic-revisions-unused-imports`: Alembic revision files are exempt from ruff lint rules, because they must stay exactly as Alembic generates them. (advisory: ruff per-file ignore of ALL for `migrations/*/versions/*.py`, not blocking)
- `api.quality.environment-variables-load`: Required environment variables and credentials load in a deployed-like environment. (blocking: CI job `test_env_vars`)
- `api.quality.mypy-v2`: Shared query models, FastAPI dependencies, v2 routes and services, and the user sign-in and account-deletion libraries pass mypy with untyped definitions disallowed. (blocking: mypy)
- `api.quality.ruff-format`: All Python files are formatted with ruff format. (blocking: ruff format)
- `api.quality.ruff-lint`: All Python code passes ruff check with every rule family selected in pyproject.toml, with no ratchet; families are added one themed group at a time until the selection is ALL. (blocking: ruff check (ANN, E4, E7, E9, F, FLY, FURB, I, PIE, PYI, RET, RSE, TC, UP, W))
- `api.quality.runtime-evaluated-models-resolve`: Every package model class that other models inherit from is listed in ruff's runtime-evaluated-base-classes, and every Pydantic model and SQLAlchemy mapper resolves its annotations once the package is imported. (blocking: pytest `tests/unit/test_runtime_evaluated_annotations.py`)
- `api.quality.tests-pass`: The unit, contract and to-refactor test suites pass. (blocking: CI job `test`)
- `api.quality.tests-ruff-exemptions`: Test files may use pytest's bare assert and need no docstrings, annotations or named constants for magic numbers (S101, D1, ANN, PLR2004); every other ruff rule applies to tests. (blocking: ruff per-file ignore of ANN, D1, PLR2004, S101 for `**/tests/**`)

### Observability

- `api.observability.id-is-diagnostic-only`: observability_id is used only to query diagnostic records, never for idempotency, cache ownership, authorization, database identity, routing or calculation behavior. (doc-only, not checked: follow it yourself)
- `api.observability.registered-stages-only`: Span names come from the stage plans in policyengine_api.observability.stages; route and service code never adds span-name string literals. (doc-only, not checked: follow it yourself)

### CI workflows and scripts

- `api.ci.multiline-run-is-script`: A GitHub Actions run: block holds one line of code and no chained commands (&&, ||, ;); anything more lives in a tested script under .github/scripts/, called from a single-line step. (blocking: quality guard `ci-scripts`)
- `api.ci.shell-scripts-pass-shellcheck`: Every shell script under .github/scripts/ passes shellcheck. (blocking: quality guard `ci-scripts`)
- `api.ci.workflow-scripts-tested`: Every shell script a workflow calls is run by at least one test. (blocking: quality guard `ci-scripts`)

### Process and repository hygiene

- `api.agents.adapters-point-to-agents-md`: CLAUDE.md and .github/copilot-instructions.md only point to AGENTS.md; skills and rules are listed in AGENTS.md alone. (blocking: quality guard `rules-registry`)
- `api.process.agents-never-bypass`: Agents never bypass branch rules, even with admin credentials: no gh pr merge --admin and no bypass option; a blocked merge is reported to a human. (doc-only, not checked: follow it yourself)
- `api.process.changelog-fragment`: Every PR adds a changelog.d fragment. (blocking: CI job `check-changelog`)
- `api.process.cloud-run-image-builds`: The Cloud Run container image builds. (blocking: CI job `test_cloud_run_container_builds`)
- `api.process.docker-image-builds`: The API Docker image builds. (blocking: CI job `test_container_builds`)
- `api.process.makefile-phony`: Command-only Makefile targets are declared in .PHONY, and .PHONY stays in sync when targets are renamed or removed. (doc-only, not checked: follow it yourself)
- `api.process.pr-tracking-issue`: Every PR has a tracking issue in this repository, and the first line of its description is Fixes #ISSUE_NUMBER. (doc-only, not checked: follow it yourself)
- `api.process.rule-machinery-code-owned`: Changes to the rule machinery (rules/, scripts/rules/, scripts/guards/, scripts/run_quality_guards.py and CODEOWNERS) need approval from a core developer other than the author. (doc-only, not checked: follow it yourself)
- `api.process.rules-registry`: Every rule is registered in rules/registry.toml, is enforced where it claims to be, and its rendered views are current. (blocking: quality guard `rules-registry`)
- `api.process.stacked-prs-full-ci-at-bottom`: In a stack of pull requests, only the lowest unmerged one runs the full PR workflow. Every pr.yml job is needed by the CI complete gate, which fails on the pull requests above it and otherwise passes only when every job passed, so a stack merges bottom-up and nothing merges untested. (blocking: pytest `tests/unit/test_ci_complete_gate.py`)

<!-- END GENERATED: rules -->
