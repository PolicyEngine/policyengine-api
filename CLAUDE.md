# PolicyEngine API

## Local workflow

- In a fresh checkout or worktree, run `make bootstrap-dev`.
- Prefer repo-native commands over hardcoded tool paths.
- Use `make lint`, `make format`, `make check-changelog`, `make pre-pr`, and `make test`.
- Do not invoke tools via paths like `./.venv/bin/ruff` or `./.venv/bin/pytest`.

## Pull requests

- Run `make pre-pr` before pushing a PR update.
- Add a changelog fragment in `changelog.d/` using one of: `added`, `changed`, `fixed`, `removed`, `breaking`.
