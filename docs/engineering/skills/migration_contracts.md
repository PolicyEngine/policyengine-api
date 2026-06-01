# Migration Contracts

Use this skill when changing API v2 migration contracts, route-group migration
metadata, generated migration docs, or guard scripts.

## Sources Of Truth

- `policyengine_api/migration_registry.py` defines route groups, path segments,
  database entities, and simulation flows used by migration flags and request
  logging.
- `tests/contract/registry.py` defines app-v2 user workflows and stable route
  response fields that must be preserved while the migration is staged.
- `scripts/export_migration_contracts.py` merges those sources into:
  - `docs/generated/migration_contracts.json`
  - `docs/engineering/migration-contracts.md`

Generated migration artifacts are checked-in review material. If a PR changes a
route group, workflow contract, stable response field, or future owner PR, run
the exporter and commit the regenerated files in the same PR.

## Update Workflow

```bash
python scripts/export_migration_contracts.py
python scripts/run_quality_guards.py
python -m pytest tests/contract tests/unit/test_migration_contract_artifacts.py -q
```

The migration-contracts guard checks that workflow names and route requests are
unique, every contract route group is declared in the migration registry, stable
response fields are present, and generated artifacts match the current
registry.

## Annotation Rules

Keep contract metadata explicit and durable:

- Use stable route-group names that match the migration flag environment
  surface.
- Record the current user-facing contract, not an aspirational target.
- Keep `future_owner_pr` at the granularity of the migration plan so reviewers
  can tell which later PR owns each workflow.
- Add only response fields that are meaningful user-facing compatibility
  anchors.
- If a route intentionally changes its API contract, update the generated docs
  and call that out in the PR description.
