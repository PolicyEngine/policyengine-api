# Dependencies and uv.lock

Read this before adding or changing anything that installs Python packages:
a workflow step, a script under `.github/`, a Makefile target, a Dockerfile,
a Modal image, `pyproject.toml` or `uv.lock`.

The Cloud Run image installs exactly the versions in `uv.lock`
(`uv sync --frozen` in `gcp/cloud_run/Dockerfile`). Everything else installs
and tests the same versions, so that CI tests what production runs. Four rules
say how; the `locked-installs` quality guard (`scripts/rules/locked_installs.py`)
checks all four in the pull request `quality-guards` job. A fifth rule,
[below](#we-declare-what-we-import), checks that `pyproject.toml` declares what
the package imports.

## We use uv.lock

`api.dependencies.lock-committed`: every directory with a `pyproject.toml` has
a committed `uv.lock` beside it, and a pull request CI job runs
`uv lock --check` for it. After changing `pyproject.toml`, run `uv lock` and
commit `uv.lock`.

## We install from uv.lock

`api.dependencies.install-from-lock`: every install of Python packages installs
exactly what `uv.lock` pins:

- `uv sync --frozen` (or `--locked`) to create the environment;
- `uv run --frozen` (or `--locked`) to run a command in it;
- in a Modal image, `Image.uv_sync(..., frozen=True)`.

The guard reports every other installer: `pip install`, `uv pip install`,
`uv sync` or `uv run` without `--frozen`/`--locked`, `uv run --with` or
`--no-project`, `uvx`, `uv tool`, `pipx`, `uv add`, `poetry`, `conda`, and
Modal's `pip_install`, `uv_pip_install` and `pip_install_from_*`. It scans
workflow `run:` blocks, every tracked shell script, Makefile recipes,
Dockerfiles and Python modules outside `tests/` (for Modal image calls and
installer subprocess calls). `add_local_python_source` copies local source
into a Modal image; it installs no packages, so the guard does not report it.

## We test from uv.lock

`api.dependencies.test-from-lock`: every `pytest`, `coverage run`,
`python -m unittest`, `tox` or `nox` command in those files runs through
`uv run --frozen`. CI jobs also set `UV_PYTHON: "3.12"`; see
[testing.md](testing.md#test-environment).

## We relock on a schedule

`api.dependencies.scheduled-relock`: a workflow on a `schedule` trigger relocks
every `uv.lock` with upgrades and opens or updates a pull request, whose CI
tests the new versions. Here it is `.github/workflows/relock-dependencies.yml`.
The guard reads the workflow's configuration and the scripts its jobs run; it
does not run the workflow.

## We declare what we import

`api.dependencies.declared-and-used`: `pyproject.toml` declares the
distributions `policyengine_api` imports, and nothing it doesn't use. The
`declared-dependencies` quality guard (`scripts/rules/declared_dependencies.py`)
runs [deptry](https://deptry.com/) on `policyengine_api` in the uv.lock
environment (`uv run --frozen --extra dev`) and fails on:

- **DEP001**: an import that no declared distribution provides;
- **DEP002**: a declared runtime dependency that the package never imports;
- **DEP003**: an import of a module installed only because another package
  depends on it, such as `starlette` through FastAPI. Declare it, so a change
  to the other package can't remove it;
- **DEP004**: an import of a package declared only in the `dev` extra;
- **DEP005**: a standard-library module declared as a dependency.

Each error message says how to fix the finding. Run the guard with
`python scripts/run_quality_guards.py`.

The rule is ratcheted: `rules/baselines/deptry.txt` lists today's findings as
`<code> <module>`, one per line, and a finding not listed there fails. The list
may only shrink. Fixing a finding makes its line fail as stale, so remove the
line and lower `count` in the rule's `[rule.baseline]`.

A declared package that the application loads by name, not by import, is a
`[[rule.exception]]` on the rule, with
`category = "not-imported-package"`, `match` set to the package's name as
`pyproject.toml` writes it (without extras or version), and `path` set to the
file that loads it. Today these are gunicorn
and uvicorn, which `gcp/cloud_run/start.sh` runs, and pymysql, the driver
`policyengine_api/data/orm.py` names. An exception covers only that package's
DEP002 finding, and fails once the file stops naming the package or deptry
stops reporting it.

deptry's settings are `[tool.deptry]` in `pyproject.toml`. The guard fails
unless that table holds exactly `known_first_party = ["policyengine_api"]` and
`pep621_dev_dependency_groups = ["dev"]`, so a tolerated finding is never
hidden in a deptry ignore setting.

## Exceptions

An install that cannot use `uv.lock` yet is a `[[rule.exception]]` on
`api.dependencies.install-from-lock` (or `api.dependencies.test-from-lock`) in
`rules/registry.toml`. Each one names one site and says why and until when:

```toml
[[rule.exception]]
path = "docker/Dockerfile"                   # the file
match = 'pip install "policyengine[models]=='  # text from the one command it covers
reason = "Why this install cannot use uv.lock."
removal = "The condition under which the exception is removed."
```

- `match` is required: an exception without one is rejected. Choose text
  that survives version bumps (leave the version out).
- Give `removal`, or a review date `expires = 2026-12-31` together with a
  tracking `issue = <number>`.
- A command-line tool installed outside the project and pinned with `==` (for
  example `pip install "shellcheck-py==0.11.0.1"`) may use
  `category = "pinned-tool"` instead of a removal condition. The guard checks
  that every package in the command is pinned with `==`.
- An exception that matches no unlocked install fails the guard; remove it
  when the install moves to `uv.lock`.

The registered exceptions are listed in
[docs/generated/rules.md](../../generated/rules.md#exceptions-and-review-dates).
