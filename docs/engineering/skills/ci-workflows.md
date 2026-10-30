# CI Workflows

Read this before adding or changing a GitHub Actions workflow step, or a script
under `.github/scripts/`.

## One line of code per `run:` block

A workflow `run:` block may hold only one line of code, with no chained
commands. Anything more goes in a shell script under `.github/scripts/`, called
from a single-line step:

```yaml
- name: Install ruff (version pinned in uv.lock)
  run: bash .github/scripts/install_locked_ruff.sh
```

Inline shell in YAML can't be linted, unit-tested or run locally; a script can.

Every non-empty, non-comment line counts, including each line of a folded
(`>`) block and each backslash-continued line. Chaining commands on one line
with `&&`, `||` or `;` also counts as more than one line. Operators inside
quotes or `${{ }}` expressions don't count, and a single pipeline (`a | b`) is
one command.

## Writing a workflow script

- Start with `#!/usr/bin/env bash` and `set -euo pipefail`.
- Take inputs from arguments or environment variables, not from `${{ }}`
  expressions inside the script.
- It must pass `shellcheck` (the `ci-scripts` quality guard runs it).

## Testing a workflow script

Every script a workflow calls must be referenced by name in at least one test.
Test it the way the existing scripts are tested: start it with `subprocess`,
put fake versions of the commands it calls (`gcloud`, `pip`, `curl`, ...) first
on `PATH`, and assert on what they were called with. Cover the success path and
at least one failure path.

Examples: `tests/unit/test_install_locked_ruff_script.py` and
`tests/unit/test_cloud_run_deploy_scripts.py`.

## Release jobs in push.yml

A release run (the run for the "Update PolicyEngine API" commit) may skip the
checks its merge run passed (`check-release-commit`, `.github/release_commit.py`).
GitHub skips a job whose needs include a skipped job, directly or through the
jobs between them, unless its `if:` calls a status function. So every release
job with `needs` starts its `if:` with `!cancelled()` and checks the result of
each job it needs, and each job of a reusable workflow a release job calls has
`if: ${{ !cancelled() }}`:

```yaml
    needs:
      - migrate-v1-production-cloud-sql
      - seed-v2-production-database
    if: |
      !cancelled()
      && (github.repository == 'PolicyEngine/policyengine-api')
      && (github.event.head_commit.message == 'Update PolicyEngine API')
      && needs.migrate-v1-production-cloud-sql.result == 'success'
      && needs.seed-v2-production-database.result == 'success'
```

Only `publish-git-tag` needs the checks that may be skipped; its
`release_commit.py require-checks` step decides whether their results let the
release continue. `tests/unit/test_release_run_checks.py` checks all of this.
A release job that left the status check to GitHub would be skipped whenever
the checks were, and the run would still finish green.

## Enforcement and baselines

The `ci-scripts` quality guard (`python scripts/run_quality_guards.py`, or
`python -m scripts.rules ci-scripts`) checks all three rules above. Existing
violations are listed in `rules/baselines/ci-*.txt`. Anything new fails, and so
does a baseline entry that no longer applies, so each list only shrinks. When
you convert an existing multi-line block into a script, or add a missing test,
remove its baseline entry and lower the rule's `baseline.count` in
`rules/registry.toml`.
