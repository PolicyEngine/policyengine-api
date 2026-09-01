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

## GitHub PRs

Read `docs/engineering/skills/github-prs.md` before opening, replacing, or
sharing any pull request.

Before creating or sharing a migration PR, run the focused migration guards:

```bash
python scripts/run_quality_guards.py
python scripts/export_migration_contracts.py
```
