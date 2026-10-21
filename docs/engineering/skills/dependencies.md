# Dependencies and uv.lock

Read this before adding or changing anything that installs Python packages:
a workflow step, a script under `.github/`, a Makefile target, a Dockerfile,
a Modal image, `pyproject.toml` or `uv.lock`.

The Cloud Run image installs exactly the versions in `uv.lock`
(`uv sync --frozen` in `gcp/cloud_run/Dockerfile`). Everything else installs
and tests the same versions, so that CI tests what production runs. Four rules
say how; the `locked-installs` quality guard (`scripts/rules/locked_installs.py`)
checks all four in the pull request `quality-guards` job.

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
