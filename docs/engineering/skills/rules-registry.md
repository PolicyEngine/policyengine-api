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
python -m scripts.rules guard --base-ref origin/<default-branch>   # everything CI checks
python -m unittest discover -s scripts/rules/tests -t .            # the tool's own tests
```

All commands use only the standard library, so they run without installing the
project.

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
| `[[rule.ci]]` | `workflow`, `job`, and an `invocation` string that must appear in that job's `run:` text (or its reusable-workflow `uses:`). |
| `[rule.proof]` | Optional; see "Proof". |
| `[rule.baseline]` | Only for `ratcheted` rules: `file` listing tolerated violations, and their `count`. |
| `[[rule.exception]]` | Temporary carve-out: `path`, `reason`, `expires`. |
| `[rule.downgrade]` | Required `reason` when a rule moves from enforced/ratcheted to advisory/doc-only. |

`blocking` is derived, never declared: a rule blocks merges when its status is
`enforced` or `ratcheted` and its tier is not `judgment`.

### Enforcer kinds

| Kind | Fields | Resolved by the guard |
| --- | --- | --- |
| `pytest` | `nodes` (`path::test` or `path::Class::test`), optional `project` (sub-project directory the paths are relative to) | Each test exists, and the CI job's command collects it |
| `quality-guard` | `name`, optional `runner` | The name is in `GUARDS` in `scripts/run_quality_guards.py` |
| `ruff` | `mode` = `format`, `lint` (with `codes`) or `per-file-ignore` (with `pattern`, `codes`) | Codes are selected / the ignore entry exists |
| `mypy` | `paths` | Each path is in `[tool.mypy].files` |
| `workflow-job` | optional `step` | The CI job exists (the job itself is the check) |
| `pyright`, `import-linter` | `config` (+ `contract` for Import Linter) | The config file exists |
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

Where possible, make the bad fixture a real past mistake from git history.
Blocking rules without proof are listed as "unproven" in `rules.md`; they don't
fail the guard yet.

## Baselines

- **Ruff is never ratcheted.** Adopting a ruff rule family is one standalone PR
  that changes the select list and fixes every resulting violation. Don't use
  `--add-noqa` or blanket per-file ignores.
- Other enforcers (mypy, Pyright, Import Linter, custom guards) may start
  `ratcheted` with a baseline file of tolerated violations. Baselines may only
  shrink: the guard compares counts against the base branch.
- Moving a rule from enforced/ratcheted to advisory/doc-only needs an explicit
  `[rule.downgrade] reason`.

## Hidden rules

The guard fails when something enforces a rule that the registry doesn't
describe:

- a `GUARDS` entry in `scripts/run_quality_guards.py`;
- a ruff format check in CI, an explicitly selected ruff code, or a ruff
  per-file ignore;
- a `[tool.mypy].files` entry;
- a test matching `[discovery].guard_test_globs` or listed in
  `extra_guard_tests`;
- a job in a `[discovery].workflows` file.

Register it, or list it under `discovery.ignore_jobs` / `discovery.ignore_tests`
with a reason.

## Keeping the tool in sync

`scripts/rules/` is byte-identical in policyengine-api and policyengine-sim-api;
see `scripts/rules/SYNC.md`. Change it in both repositories together and bump
`TOOL_VERSION` and each registry's `tool_version`.
