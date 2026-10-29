# GitHub PRs

Use this skill before opening, replacing, or sharing a pull request.

## Tracking Issues

Before opening a PR, all developers and agents must:

1. Open a GitHub issue for the work in `PolicyEngine/policyengine-api`, or
   verify that an appropriate issue already exists.
2. Put `Fixes #ISSUE_NUMBER` as the first line of the PR description, using the
   issue number from the previous step. The PR template starts with this line.

## Changelog fragments

Every PR adds at least one changelog fragment of its own
(`api.process.changelog-fragment`). A fragment is a file directly in
`changelog.d/`, named `changelog.d/<name>.<type>.md`:

- `<type>` is one of the types in `[tool.towncrier]` in `pyproject.toml`:
  `breaking`, `added`, `changed`, `fixed` or `removed`, in lowercase. It sets
  the release's version bump: `breaking` raises the major version, `added` and
  `removed` the minor version, and `changed` and `fixed` the patch version.
- `<name>` is letters and digits, in groups joined by single dots, hyphens or
  underscores: an issue number such as `4083`, or a short label such as
  `report-live-since`. A branch name with a `/` in it makes a folder, which
  doesn't count.
- The file holds a sentence or two, in UTF-8, saying what changed for people
  who use or run the Public API. An empty file, or one with only whitespace,
  fails.

For example:

```bash
echo 'Report when the deployed version went live.' > changelog.d/4083.added.md
```

The `Check changelog fragment` job in `pr.yml` compares the PR with its base
commit (`github.event.pull_request.base.sha`):

- It fails unless the PR adds such a file. Fragments already on master don't
  count: they belong to the PRs that added them until the next release removes
  them. Editing, deleting or renaming one of them doesn't count either, but
  moving a file the release couldn't read to a fragment name does.
- It fails on every file in `changelog.d/` the release can't read: a file in a
  folder (#4084's `changelog.d/added/4083.md` belonged at
  `changelog.d/4083.added.md`), another name, an unknown or uppercase type, an
  empty file, a symbolic link or a submodule. Each error says how to fix it.

After a merge to master, the `versioning` job in `push.yml` runs
`.github/bump_version.py` and then Towncrier. The bump reads fragments through
the same definition as the check, `.github/changelog_fragments.py`, and stops
at any file it can't read; `ignore = [".gitkeep"]` makes Towncrier stop too.
A release therefore never leaves out a fragment.

To run the check locally before pushing:

```bash
BASE_SHA=origin/master bash .github/scripts/check_changelog_fragment.sh
```

## Branch Rules

Agents must never bypass branch rules, even when their credentials have admin
rights: do not merge with `gh pr merge --admin`, and do not use GitHub's option
to bypass rules. If a required check or review blocks a merge, report it to a
human instead.

## Stacked PRs and CI

In a stack of pull requests, only the lowest unmerged one runs the full PR
workflow (`.github/workflows/pr.yml`). The ones above it run only the
`CI complete` job, which fails and says so. A stack therefore uses one set of
runners instead of one per layer.

- **`CI complete` is the required check.** It needs every other job. On a
  pull request that isn't stacked, or is the lowest unmerged one, it passes
  only when every job passed. Skipped jobs would otherwise count as passing, so
  a stack can only merge bottom-up, and nothing merges untested.
- **When the pull request below merges,** GitHub rebases the next one onto
  the trunk, and that push starts its full run. If no run starts, push again
  (`gh stack rebase`, then `gh stack push`), or close and reopen the pull
  request. Re-running the old workflow doesn't help: it reuses the old event,
  which still describes the pull request as higher in the stack.
- **When you add a job to `pr.yml`,** add it to `CI complete`'s `needs`. If
  the job has no `needs` of its own, also give it the same stack condition as
  the other jobs. `tests/unit/test_ci_complete_gate.py` checks both.

## Migration PRs

Migration PRs should keep the user experience stable unless the PR explicitly
declares an API contract change. If a PR changes migration route contracts,
route-group metadata, generated migration artifacts, or the cutover guardrails,
it should:

1. Include a changelog fragment (see
   [Changelog fragments](#changelog-fragments)).
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

For any PR that adds inline ruff suppressions (`# noqa`), list each one with
the reason a code change or ruff setting couldn't remove the finding
(`api.process.agents-suppress-as-last-resort`).

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
