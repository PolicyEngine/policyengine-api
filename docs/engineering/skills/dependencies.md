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

- **DEP001**: an import whose top-level module no declared distribution
  provides. deptry checks only the top-level name, so `from google.cloud
  import bigquery` passes while any declared distribution provides
  `google`;
- **DEP002**: a declared runtime dependency that the package never imports;
- **DEP003**: an import of a module installed only because another package
  depends on it, such as `starlette` through FastAPI. Declare it, so a change
  to the other package can't remove it;
- **DEP004**: an import of a package declared only as a development
  dependency: in the `dev` extra or a `[dependency-groups]` group;
- **DEP005**: a standard-library module declared as a dependency.

Each error message says how to fix the finding. Run the guard with
`python scripts/run_quality_guards.py`. It runs deptry on Python 3.12, as
`make install` does, unless `UV_PYTHON` says otherwise, and uv first syncs
`.venv` to `uv.lock`: a `.venv` on another Python, or without the `dev` extra,
is rebuilt. The pull request and merge `quality-guards` jobs install uv and
sync the environment before the guard runs.

The rule is ratcheted: `rules/baselines/deptry.txt` lists today's findings as
`<code> <module>`, one per line, and a finding not listed there fails. Comments
go on lines of their own. The list may only shrink: the registry guard fails a
pull request whose baseline has a higher count than the base branch's, or any
entry the base branch's copy doesn't. Fixing a finding makes its line fail as
stale, so remove the line and lower `count` in the rule's `[rule.baseline]`.
An entry can't be renamed either: if the name deptry reports changes (because
`pyproject.toml` respells the package, or a deptry upgrade normalizes names),
the new name fails as an entry the base branch lacks, so fix the finding in
the same change.

A declared package that the application loads by name, not by import, is a
`[[rule.exception]]` on the rule, with
`category = "not-imported-package"`, `match` set to the package's name as
`pyproject.toml` writes it (without extras or version), and `path` set to the
file that loads it. Today these are gunicorn
and uvicorn, which `gcp/cloud_run/start.sh` runs, and pymysql, the driver
`policyengine_api/data/orm.py` names. An exception covers only that package's
DEP002 finding. Its `path` must be one file's exact path from the repository
root, not a glob, and a file the application runs from: a shell script, a
Dockerfile or a module in `policyengine_api`. Any other file, such as
`pyproject.toml`, the registry or a changelog fragment, can mention a package
without loading it. The exception fails once no line in the file other than a
whole-line comment names the package, or once deptry stops reporting it.

An exception is reviewed like the baseline, since both are in code-owned
`rules/`, but it isn't counted: add one only for a package the application
really loads by name, never to tolerate an unused dependency.

A tolerated finding lives only in the baseline or an exception, both
code-owned. The guard also fails on anything else that would hide a finding
from deptry:

- `[tool.deptry]` in `pyproject.toml` holding anything but
  `known_first_party = ["policyengine_api"]` and
  `optional_dependencies_dev_groups = ["dev"]`;
- a `[project.optional-dependencies]` group other than `dev`. deptry counts
  such a group as runtime dependencies, but the Cloud Run image installs no
  extras, so declare a runtime dependency in `[project].dependencies`;
- a `[project].dependencies` entry with an environment marker. deptry ignores
  markers, so a marker that never holds would declare a package that uv never
  installs;
- an inline `# deptry: ignore` comment in `policyengine_api`;
- a tracked file in `policyengine_api` that deptry didn't scan, because a
  `.gitignore`, `.git/info/exclude`, the global git excludes file, or an
  `.ignore` file in its directory or a parent directory lists it. The guard
  compares the files deptry's verbose log says it scanned with `git ls-files`;
- a file in `policyengine_api` that deptry couldn't parse, which it skips with
  a warning.

The guard can't see one more case: deptry treats every module and directory
directly in `policyengine_api/` (`api`, `utils`, `data`, ...) as the project's
own, so a new `policyengine_api/redis.py` would make `import redis` look
local. Don't name a top-level module of the package after a third-party
package.

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
