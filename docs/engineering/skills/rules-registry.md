# Rules Registry

Read this before adding, changing, relaxing or removing a rule, a guard test, a
checker configuration (ruff, mypy, Pyright, Import Linter), or a CI job that
enforces one.

Every rule that governs this repository lives in `rules/registry.toml`. The
registry says what each rule requires, how mechanically it is enforced, which
CI job runs it, and whether its checker has been proven to reject a bad example.
`python -m scripts.rules render` turns it into `docs/generated/rules.md` and the
Rules block in `AGENTS.md`; the `rules-registry` quality guard fails CI when the
registry, the checkers and the rendered views disagree.

## Commands

```bash
python -m scripts.rules validate                    # schema and file checks only
python -m scripts.rules render                      # rewrite rules.md and the AGENTS.md block
python -m scripts.rules guard --base-ref "$(git merge-base HEAD origin/<default-branch>)"   # everything CI checks
python -m unittest discover -s scripts/rules/tests -t .            # the tool's own tests
```

All commands use only the standard library, so they run without installing the
project, except the `declared-dependencies` guard and its tests in the tool's
tests. They run deptry through `uv run --frozen --extra dev`, so they need uv,
and uv first syncs `.venv` to `uv.lock` on Python 3.12
([dependencies.md](dependencies.md#we-declare-what-we-import)).

## Adding or changing a rule

A PR that adds, tightens or relaxes a rule contains all of these:

1. **The check**: the checker, config or test change.
2. **A registry entry** (fields below).
3. **Proof, appropriate to the tier**: see "Proof".
4. **Zero violations, or a baseline** where the baseline policy allows one.
5. **CI wiring**: a `[[rule.ci]]` reference to the job that runs the check.
6. **Doc update**: explanatory skills docs cite the rule id instead of
   restating the rule as unchecked prose.
7. **Regenerated outputs**: run `python -m scripts.rules render` and commit
   `docs/generated/rules.md` and `AGENTS.md`.

If a rule exists only in prose, register it with `status = "doc-only"` so the
gap is visible, rather than leaving it out.

## Fields

| Field | Meaning |
| --- | --- |
| `id` | Lowercase dotted id, e.g. `api.v2.services-no-sql`. Never reuse an id. |
| `category` | One of the `[[category]]` ids; controls grouping in the rendered views. |
| `statement` | One plain-English sentence an agent can follow. |
| `rationale` | Path (optionally `#anchor`) to the doc that explains the rule. |
| `scope` | Globs for the files the rule constrains; each must match a file. |
| `tier` | How mechanically the rule can be checked (see "Tiers"). |
| `status` | `enforced`, `ratcheted`, `advisory` or `doc-only`. |
| `autofix` | Whether the enforcer can fix violations itself (e.g. ruff format). |
| `review_by` | Optional date; the guard fails once it passes. |
| `[rule.enforcer]` | What checks the rule; `kind` plus kind-specific fields. |
| `[[rule.ci]]` | `workflow`, `job`, and an `invocation` string that must appear in that job's `run:` text (or its reusable-workflow `uses:`), or in a command of a Makefile target the job runs with `make <target>`, following the targets' prerequisites and the `$(MAKE)` calls in their recipes (`scripts/rules/makefile.py`). |
| `[rule.proof]` | Optional; see "Proof". |
| `[rule.baseline]` | Only for `ratcheted` rules: `file` listing tolerated violations, and their `count`. |
| `[[rule.exception]]` | Carve-out: `path`, `reason`, and `expires`; or, for rules whose guard reads them, `match` (one site), `removal`, `issue` and `category` ([dependencies.md](dependencies.md#exceptions); for `api.data.sqlalchemy-and-alembic-only`, `match` is the exact construct and `category` is `driver-access`, `schema-change` or `migration-revision`: [alembic-migrations.md](alembic-migrations.md#declared-exceptions)). |
| `[rule.downgrade]` | Required `reason` when a rule moves from enforced/ratcheted to advisory/doc-only. |

`blocking` is derived, never declared: a rule blocks merges when its status is
`enforced` or `ratcheted` and its tier is not `judgment`.

### Enforcer kinds

| Kind | Fields | Resolved by the guard |
| --- | --- | --- |
| `pytest` | `nodes` (`path::test` or `path::Class::test`), optional `project` (sub-project directory the paths are relative to) | Each test exists, and the CI job's command collects it |
| `quality-guard` | `name`, optional `runner` | The name is in `GUARDS` in `scripts/run_quality_guards.py` |
| `ruff` | `mode` = `format`, `lint` (with `codes`) or `per-file-ignore` (with `pattern`, `codes`) | Codes are selected / the ignore entry exists and covers only [files allowed file-level exceptions](#file-level-exceptions) |
| `mypy` | `paths` | Each path is in `[tool.mypy].files` |
| `workflow-job` | optional `step` | The CI job exists (the job itself is the check) |
| `pyright` | `config` | The config file exists |
| `import-linter` | `config`, `contract`, `contract_sha256`, optional `allowed_ignore_imports` | The contract with that `id` exists; its definition hashes to `contract_sha256`; and its `ignore_imports` equals the rule's baseline entries plus `allowed_ignore_imports`, with no wildcards and with `unmatched_ignore_imports_alerting = "error"` (see "Baselines") |
| `docs-guard` | `doc`, `marker` | The doc exists |
| `llm-review` | `prompt`, `model` | The prompt exists; judgment tier only |
| `none` | | Nothing; only for `doc-only` and `advisory` rules |

## Tiers

| Tier | Covers | Can block? | Proof |
| --- | --- | --- | --- |
| `mechanical` | A pattern is present or not | Yes | A bad fixture is rejected and a good fixture is accepted |
| `metric` | A number crosses a threshold | Yes | Fixtures just below and just above the threshold |
| `judgment` | Needs reading comprehension (LLM review plus human) | No | A labelled eval set with measured precision |

Judgment rules graduate: when the same judgment finding recurs, turn it into a
mechanical rule.

## Proof

A proof shows the checker actually rejects what the rule forbids. Put fixtures
under `rules/fixtures/<rule-id>/` and add a test named `test_rule_proof_<name>`
that runs the rule's checker on them.

| Tier | Proof fields |
| --- | --- |
| `mechanical` | `bad_fixture`, `good_fixture`, `test` (+ optional `project`) |
| `metric` | `below_fixture`, `above_fixture`, `threshold`, `test` |
| `judgment` | `eval_set`, `min_precision`, `measured_precision`, `measured_on` |

The proof test asserts that the bad fixture is rejected and the good one
accepted. The guard doesn't run it; it checks that the fixtures exist and that a
CI job collects the proof test:

- For a `pytest`-enforced rule, the proof test must be collected by the rule's
  own `[[rule.ci]]` job (for example, under the paths `make test` runs).
- For any other enforcer, name the job that runs the proof test with
  `proof.workflow`, `proof.job` and `proof.invocation` (all three or none).

Where possible, make the bad fixture a real past mistake from git history.
Blocking rules without proof are listed as "unproven" in `rules.md`; they don't
fail the guard yet.

## Baselines

- **Ruff is never ratcheted.** `select = ["ALL"]`, so every ruff rule applies
  except the four listed in `ignore` (two formatter conflicts and one of each
  mutually exclusive docstring pair) and the registered per-file ignores. When
  a ruff upgrade adds rules, the upgrade PR fixes every new violation. Don't
  use `--add-noqa`. A finding that is kept gets an inline
  `# noqa: CODE  # reason`, except in the files below.
- Other enforcers (mypy, Pyright, Import Linter, custom guards) may start
  `ratcheted` with a baseline file of tolerated violations. Baselines may only
  shrink: the guard compares each baseline's count and its entries against the
  base branch, so an entry can't be swapped for a new one at the same count.
  Entries are counted, so a baseline that lists an entry once per tolerated
  occurrence can't gain another copy of one either.
  Each entry is therefore a stable key, such as a path or a code and a module,
  never a count or a line number, which would change as violations are fixed.
- **Import Linter** tolerates a violation through the contract's
  `ignore_imports` in `pyproject.toml`. The rule's baseline file lists the same
  entries, one per line, so adding one needs a change under the code-owned
  `rules/` directory; imports the rule allows by design, rather than tolerates,
  go in `enforcer.allowed_ignore_imports`. The guard fails when the contract's
  `ignore_imports` and those two lists differ, and
  `unmatched_ignore_imports_alerting = "error"` makes Import Linter fail on an
  entry that no longer matches, so fixing an import forces the entry out.
  No entry may use a wildcard, so each names one importer and one imported
  module, and a new module's own imports never match an old entry (it can
  still reach a forbidden module through a tolerated import; see below). CI
  runs exactly `lint-imports --config pyproject.toml`, which the guard checks,
  so a `setup.cfg` or `.importlinter` file can't take the contracts' place and
  `--contract` or `|| true` can't skip them.
- `enforcer.allowed_ignore_imports` has no count limit. Moving a tolerated
  import from the baseline into it lowers the baseline's count without fixing
  anything, so code-owner review of `rules/registry.toml` is the check on it.
- An Import Linter rule also pins the rest of its contract: the SHA-256 of the
  top-level `[tool.importlinter]` settings and every contract field except
  `ignore_imports` (`scripts/rules/import_linter.py`, `contract_fingerprint`)
  must equal `enforcer.contract_sha256`. Narrowing a contract's modules, or a
  setting such as `exclude_type_checking_imports`, therefore needs a registry
  change too; the guard's message gives the new value.
- Ignoring an import removes it from the graph the contract checks, so the
  exception also covers every chain from another module that passes through
  it, including from modules added later. Each such chain goes away when the
  tolerated import is fixed.
- Each rule's proof fixture breaks the contract once per source and forbidden
  module pattern, and lists those violations in `expected_violations`; the
  proof requires Import Linter to report exactly them.
- Moving a rule from enforced/ratcheted to advisory/doc-only needs an explicit
  `[rule.downgrade] reason`.

## File-level exceptions

A ruff `per-file-ignores` entry switches rules off for whole files. It is
allowed only where that's the norm rather than an exception to it:

- **tests**: files under a `tests` or `authenticated_tests` directory;
- **CI/CD scripts**: files under `.github`;
- **command-line scripts**: files under a `scripts` directory, or modules that
  run as a program through `if __name__ == "__main__":`.

Everywhere else, fix the finding. An inline suppression is the last resort
(see "Inline suppressions").

Each entry needs a `per-file-ignore` rule (see below). The guard expands the
entry's pattern like ruff does and fails when the pattern:

- covers any other file;
- is negated;
- matches nothing.

`scripts/rules/file_exceptions.py` holds these definitions.

## Inline suppressions

An inline suppression (`# noqa: <CODE>  # reason`, or
`# type: ignore[<code>]  # reason` for mypy) is the last resort for a ruff or
mypy finding, not the usual way to clear one
(`api.process.agents-suppress-as-last-resort`). Before adding one, try:

1. **A code change** that removes the finding: narrow an `except` to the
   errors the code expects, pass the missing argument, or route repeated code
   through one helper so a boundary is handled once instead of at every call
   site.
2. **A checker setting**, when several findings share a cause: for example,
   list a lazily loaded package in ruff's `banned-module-level-imports`
   instead of suppressing each deferred import of it.
3. **A file-level exception**, only where the section above allows one.

Keep a suppression only when each of these would change behaviour that
callers rely on, or when the rule doesn't fit the code. Give the reason after
the code, as every suppression does.

For a deliberate best-effort call whose failure must be ignored, use
`with contextlib.suppress(Exception):` with the reason in a comment above it,
the form ruff's `SIM105` recommends, instead of `try`/`except Exception: pass`
with suppressions. It still ignores every exception, so it needs the same
justification as a suppression.

A pull request that adds inline suppressions lists each one in its
description, with the reason a code change or setting wasn't used.

### The form of a suppression

`api.quality.suppressions-explained`: every `noqa`, `ruff: disable` and
`type: ignore` comment names what it suppresses and says why. The
`suppressions` quality guard (`scripts/rules/suppressions.py`) reads every
tracked `.py` and `.pyi` file with `tokenize`, so only real comments count,
and fails on a suppression that lacks either:

- **a code**: `# noqa` and its file-level forms `# ruff: noqa` and
  `# flake8: noqa` list ruff codes (`# noqa: E402`), a range suppression
  `# ruff: disable[T201]` lists ruff codes in brackets (its closing
  `# ruff: enable[T201]` needs neither), so does ruff's trailing
  `# ruff: ignore[E501]` (a preview feature in ruff 0.15), and
  `# type: ignore` lists mypy error codes (`# type: ignore[arg-type]`).
  Brackets that hold no code, such as `[]` or `[,]`, name none: mypy then
  ignores every error on the line. As in mypy, `type: ignore` counts only at
  the start of a comment and with no space before its colon;
- **a reason**: another `#` part of the same comment that is neither a
  suppression nor another tool's directive, such as `fmt: skip`,
  `pragma: no cover`, `pyright: ignore`, `nosec` or `mypy: ignore-errors`:
  `# noqa: E402  # the path setup must run first` or
  `# type: ignore[arg-type]  # the stub's annotation is too narrow`. The
  guard recognizes a directive only when the whole part is in its tool's
  syntax, so a reason may start with a tool's name and a colon
  (`# mypy: the plugin can't see it`, `# fmt: on purpose, the columns line
  up`). A type comment at the start of the comment (`# type: list[int]`)
  isn't a reason either. Text after the codes in the same part
  (`# noqa: E402 path setup`) doesn't count. Put the reason after
  `type: ignore`, which mypy reads only at the start of a comment.

The rule is ratcheted. `rules/baselines/suppressions.txt` lists today's
unexplained suppressions as `<path> :: <source line>`, one line per
occurrence. A suppression not listed there fails, and a listed one that is
gone or now explained fails as stale, so give it its reason, remove its line
and lower the rule's baseline `count`. Editing a listed line, or renaming or
moving its file, also makes it fail, because its entry no longer matches and
the registry guard rejects an entry the base branch's baseline lacks: add the
reason in the same change. So does `ruff format` rewriting a listed line.

Ruff's PGH003 and PGH004, selected with every other ruff rule, already reject
a `type: ignore` or a line-level or file-level `noqa` without a code. PGH003
accepts `# type: ignore[]`, which mypy treats as ignoring every error on the
line; this rule rejects it, and `[,]`. What the rule adds is the reason.
Other tools' comments that switch a check off, such as `# mypy: ignore-errors`
or `# isort: skip_file`, are not checked, and neither are notebooks
(`.ipynb`), which the repository has none of. Whether the suppression should exist at
all is still the judgment rule `api.process.agents-suppress-as-last-resort`
above.

## Hidden rules

The guard fails when something enforces a rule that the registry doesn't
describe:

- a `GUARDS` entry in `scripts/run_quality_guards.py`;
- a ruff format check in CI, an explicitly selected ruff code, or a ruff
  per-file ignore;
- a `[tool.mypy].files` entry;
- an Import Linter contract in `pyproject.toml`;
- a test matching `[discovery].guard_test_globs` or listed in
  `extra_guard_tests`;
- a job in a `[discovery].workflows` file.

Register it, or list it under `discovery.ignore_jobs` / `discovery.ignore_tests`
with a reason.

## The tool in other repositories

policyengine-sim-api has its own copy of `scripts/rules/`, which started as this
one. The copies may diverge: each repository owns its copy. Port a change by
hand when it's useful in both.
