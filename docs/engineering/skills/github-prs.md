# GitHub PRs

Use this skill before opening, replacing, or sharing a pull request.

## Tracking Issues

Before opening a PR, all developers and agents must:

1. Open a GitHub issue for the work in `PolicyEngine/policyengine-api`, or
   verify that an appropriate issue already exists.
2. Put `Fixes #ISSUE_NUMBER` as the first line of the PR description, using the
   issue number from the previous step. The PR template starts with this line.

Rule `api.process.pr-tracking-issue`. The `PR description` job, in
`.github/workflows/pr-description.yml`, checks every open pull request whenever
it is opened, reopened or edited and on every push, including each pull request
in a stack. It skips closed pull requests. It reads the description from the
event that started the run and fails unless:

- the first line is exactly `Fixes #ISSUE_NUMBER`;
- `ISSUE_NUMBER` is an open issue in this repository. A pull request's number,
  an issue that was moved to another repository, a closed issue and a number
  with no issue all fail.

CRLF line endings, which the GitHub web editor uses, and trailing spaces are
fine. These fail:

- an empty description, or the template's `Fixes #` left unfilled;
- a blank first line, or leading spaces before `Fixes`;
- other wording, such as `Fixes #3728.`, `Closes #3800.` or `Part of #3797`;
- a reference to another repository, such as
  `Fixes PolicyEngine/policyengine-sim-api#862`.

To fix a failure:

- **Wrong first line:** edit the description. Saving the edit runs the check
  again.
- **Closed issue:** if the pull request still fixes it, reopen the issue, then
  re-run the job from the pull request's Checks tab. Reopening an issue starts
  no run. Re-running checks the description as it was when the run started, so
  after changing the description, rely on the run the edit starts.

A pull request into a branch that doesn't contain
`.github/scripts/check_pr_description.py`, such as one stacked on a branch cut
before the check existed, fails with Python's `can't open file` message. Merge
master into that branch, or rely on the run that starts when GitHub retargets
the pull request to master.

To run the check on a description locally, save a pull request event and pass
it in; the check needs only Python and an authenticated `gh`:

```bash
gh pr view <PR_NUMBER> --json body --jq '{pull_request: {body: .body}}' > /tmp/event.json
GITHUB_EVENT_PATH=/tmp/event.json GITHUB_REPOSITORY=PolicyEngine/policyengine-api \
  python .github/scripts/check_pr_description.py
```

Automated pull requests follow the rule too:

- The PolicyEngine bundle update (`update-policyengine-package.sh`) reuses the
  oldest open "Update PolicyEngine bundle to <version>" issue or opens one, so
  each version's pull request has an issue of its own. Merging the pull
  request closes it. Closing the pull request without merging, as when a
  newer version supersedes it, runs `close-bundle-update-issue.yml`, which
  closes it too, even when the pull request conflicts with master (the
  workflow runs on `pull_request_target`). If you reopen such a pull request,
  reopen its issue as well, then re-run its `PR description` job. A run that
  opens an issue but then can't push or open the pull request closes that
  issue again.
- A bundle-update pull request opened before the rule has no `Fixes` line,
  and rerunning the workflow doesn't add one: edit its description.
- The daily relock (`open_relock_pull_request.sh`) reuses the open "Relock
  dependencies" issue or opens one, and rewrites the description of a relock
  pull request that is already open.

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
  who use or run the Public API. An empty file, or one with only whitespace
  or invisible characters such as a zero-width space, fails.

For example:

```bash
echo 'Report when the deployed version went live.' > changelog.d/4083.added.md
```

The `Check changelog fragment` job in `pr.yml` compares the PR with its base
commit (`github.event.pull_request.base.sha`):

- It fails unless the PR adds such a file. Fragments already on master don't
  count: they belong to the PRs that added them until the next release removes
  them. Editing, deleting or renaming one of them doesn't count either, but
  moving a file the release couldn't read to a fragment name does. git decides
  what is a rename: a file deleted and one added with mostly the same text.
- A fragment the base branch has already released doesn't count, and fails.
  When a lower PR in a stack is squash-merged, the release removes its
  fragment; an upper branch that still holds the lower PR's commits would add
  it back with the same text. Rebase the upper branch onto master without
  those commits. A new fragment that only reuses a released one's name counts.
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
`CI complete` job, which fails and says so, and the `PR description` job (see
[Tracking Issues](#tracking-issues)), which every open pull request runs. A
stack therefore uses one set of runners instead of one per layer.

- **`CI complete` is the required check for `pr.yml`.** It needs every other
  job. On a pull request that isn't stacked, or is the lowest unmerged one, it
  passes only when every job passed. Skipped jobs would otherwise count as
  passing, so a stack can only merge bottom-up, and nothing merges untested.
- **`PR description` is in a workflow of its own,** so `CI complete` can't
  need it, and it has no stack condition. For it to block a merge, the master
  ruleset has to require it by name, next to `CI complete`.
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

AI agents must run the quality checks before committing their own code
changes. Run `make install` once per clone: it turns on the git hooks in
`.githooks` (through `git config core.hooksPath .githooks`), which run them
before each `git commit` and each merge commit
(`api.quality.pre-commit-hook`):

```bash
make install   # once per clone, and once in each new worktree for its .venv
make quality   # what the hook runs; run it yourself to check sooner
```

`.githooks/pre-commit` runs `make quality` from the root of the working
tree, and `.githooks/pre-merge-commit` runs it for a merge that commits
without conflicts. `make quality` checks the working tree, not the commit,
so the hook first requires the two to match. It stops the commit, naming
the files and saying what to do:

- when tracked files have unstaged changes: stage them, or set them aside
  with `git stash push --keep-index`. This covers fixes `make quality` made
  in an earlier run, and `git commit <paths>` while other files are
  changed;
- when there are untracked files outside `.gitignore`: add them, remove
  them, or list them in `.git/info/exclude`;
- when a check fails;
- when ruff's fixes changed a file: review the fixes, stage them and
  commit again;
- when `make`, `uv` or the worktree's dev environment (`.venv`, or
  `UV_PROJECT_ENVIRONMENT`) is missing.

`core.hooksPath` is a setting of the clone, so every worktree runs the
hooks, each from its own checkout; a worktree on a branch from before the
hooks runs none. `make install` leaves `core.hooksPath` alone, and says
why, when it would change an enclosing repository, replace another
`core.hooksPath`, or stop the clone's own hooks in `.git/hooks`. git's
cherry-pick, revert and rebase make commits without hooks. Don't skip them
with `git commit --no-verify`; CI's `Quality checks` job runs the same
checks and blocks the merge anyway.

`make quality` applies ruff's fixes (`ruff check --fix`, then `ruff format`),
then runs `make quality-check`: `uv lock --check`, `ruff check`,
`ruff format --check`, Import Linter, mypy and the quality guards
(`scripts/run_quality_guards.py`), without changing files. Commit the fixes
it makes with your change. pr.yml's `quality-guards` job runs the same
command and fails if the fixes changed a file (`api.quality.make-quality`).
Keep the Makefile to rules, recipes and variables. The rules registry
reads it to see which checks the job runs, and gives no credit to a
Makefile that:

- uses `include`, a conditional, `define`, `$(eval ...)`, a recipe after
  `;`, or a computed target or variable name;
- sets something that can hide failures (`.IGNORE`, `.ONESHELL`,
  `MAKEFLAGS`, `GNUMAKEFLAGS`, `MAKEFILES`, `SHELL`, `.SHELLFLAGS`);
- or has a `GNUmakefile` or `makefile` beside it.

`tests/unit/test_make_quality.py` also runs `make quality` with a stand-in
for uv, and fails unless make runs every check and fails whenever one of
them fails.

A local run can still differ from CI's:

- The job also runs the rules registry tool's own tests
  (`scripts/rules/tests`), which `make quality` leaves out.
- The rules guard compares baselines and rule statuses with
  `RULES_BASE_REF`, which `make quality-check` sets to the commit `HEAD`
  shares with `origin/<base branch>`: CI's `GITHUB_BASE_REF`, or `master`
  locally. A branch is compared with where it left `master`; CI compares
  its merge with `master` with the commit that merge is built on. Without
  `origin/master`, or in a shallow clone without the merge base, git
  reports an error and the local comparison is skipped, so fetch `origin`
  with its history first.
- `uv run --frozen --extra dev` installs what the `dev` extra needs but
  removes nothing, so packages `make test` added for other groups stay in
  `.venv` and mypy, Import Linter and deptry can see them locally.
- Without `shellcheck` installed, the ci-scripts guard skips that check
  locally; CI installs it and fails without it.
- `uv lock --check` runs your uv; CI pins uv 0.13.4.
- `make quality` stops at the first failing check, so fix it and run it
  again to see the next one.

diff-cover isn't part of it: it needs every test shard's coverage report
(see the testing skill).

Commit only after `make quality` passes. If a check fails on unrelated
pre-existing issues, include that result in the handoff instead of hiding it.
