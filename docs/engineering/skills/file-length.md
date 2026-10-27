# File Length

Read this before adding code to a Python file that is close to its limit, or
before splitting a module into smaller ones.

## The limit

`api.quality.file-length`: a tracked Python file has at most 800 physical
lines, or at most 1,500 if it is test code. Test code is:

- a file under a `tests` directory;
- a test-support file under a `fixtures` directory;
- a `conftest.py`.

Every line counts, including blank lines, comments and docstrings. The
`file-length` quality guard (`python scripts/run_quality_guards.py`) measures
every Python file `git ls-files` lists.

Alembic revisions (`migrations/*/versions/*.py`) are not measured. The rule's
`[[rule.exception]]` in `rules/registry.toml` gives the reason: a revision stays
exactly as Alembic generated it, and one that has been applied has already run
against a database. Ruff excludes the same files.

Ruff has no file-length rule (it doesn't implement pylint's `C0302`), and its
size rules (complexity, branches, statements, arguments) measure one function at
a time. A file made of short functions passes all of them however long it grows.

## Splitting a file

Split a file that is over its limit, or about to be, by responsibility: each new
module holds one group of related code, such as the request parsing, the
calculation or the persistence of a service. Aim for modules of about 400 lines
where that is natural, and keep every one under the limit.

- **Move code; don't change it.** Logic, messages, outputs and the order of
  operations stay the same, so the split is reviewable as a move.
- **Keep every public import path.** Other modules and tests import names from
  the original module. Keep it as the place they come from: it imports the
  moved names from the new modules and re-exports them, listed in `__all__`.
- **Don't import a private name from another module.** If a moved helper that
  starts with an underscore is now used from a second module, rename it
  without the underscore, and list the rename in the pull request.
- **Keep tests intact.** Each test keeps its name and body, apart from imports.
- **Patch where the name is looked up.** `monkeypatch.setattr` and
  `mock.patch` replace a name in one module. If `fetch_rows` moves to a new
  module and is called there, a patch of the original module's `fetch_rows`
  no longer reaches that call, and the test silently stops using its fake.
  Patch the module whose code calls the name.

## The baseline

The rule is ratcheted: `rules/baselines/file-length.txt` lists the files that
were over their limit when the rule was added, and the guard tolerates only
those. It fails on an oversized file the baseline doesn't list, and on a listed
file that is now within its limit or no longer exists, so the list only
shrinks. When a split brings a file under its limit, remove its entry and lower
the rule's `baseline.count` in the same pull request. Never add an entry: split
the file instead.
