# GitHub PRs

Use this skill before opening, replacing, or sharing a pull request.

## Migration PRs

Migration PRs should keep the user experience stable unless the PR explicitly
declares an API contract change. If a PR changes migration route contracts,
route-group metadata, generated migration artifacts, or the cutover guardrails,
it should:

1. Include a changelog fragment.
2. Refresh generated migration artifacts with
   `python scripts/export_migration_contracts.py`.
3. Run `python scripts/run_quality_guards.py`.
4. Run the focused contract or unit tests that cover the changed surface.

## PR Descriptions

For migration work, identify:

- which route groups or workflows are covered;
- what remains on the Flask/API v1 path;
- what is newly prepared for FastAPI, SQLAlchemy/Alembic, Supabase, Cloud Run,
  or Modal migration;
- which user-visible API contract changes are intentionally introduced.

