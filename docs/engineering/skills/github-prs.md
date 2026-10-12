# GitHub PRs

Use this skill before opening, replacing, or sharing a pull request.

## Tracking Issues

Before opening a PR, all developers and agents must:

1. Open a GitHub issue for the work in `PolicyEngine/policyengine-api`, or
   verify that an appropriate issue already exists.
2. Put `Fixes #ISSUE_NUMBER` as the first line of the PR description, using the
   issue number from the previous step. The PR template starts with this line.

## Branch Rules

Agents must never bypass branch rules, even when their credentials have admin
rights: do not merge with `gh pr merge --admin`, and do not use GitHub's option
to bypass rules. If a required check or review blocks a merge, report it to a
human instead.

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

## Commit Hygiene

AI agents must run formatting and lint checks before committing their own code
changes:

```bash
make format
ruff check <changed Python files>
```

Commit only after formatting succeeds and changed Python files pass lint. If a
broader repo-wide lint command fails on unrelated pre-existing issues, include
that result in the handoff instead of hiding it.
