# Typing-Only Imports Skill

Read this before adding a Pydantic, SQLModel or SQLAlchemy model class that other
models inherit from, or before moving an import under `if TYPE_CHECKING:`.

## When an import moves

The package's modules use `from __future__ import annotations`, so Python stores
every annotation as a string and never evaluates it. An import that only
annotations use is therefore not needed at runtime, and ruff's typing-only import
rules (`TC`) move it under `if TYPE_CHECKING:`, which is `False` when the code
runs and `True` for type checkers. That removes import-time work and import
cycles without changing behaviour.

## Models that read annotations at runtime

Some libraries do evaluate those strings at runtime:

- Pydantic and SQLModel build each model's validators from its annotations.
- SQLAlchemy resolves `Mapped[...]` columns when a mapped class is configured.
- FastAPI reads endpoint signatures when routes are registered.

Names those annotations use must exist at runtime. Ruff keeps a class's
annotation imports at runtime only when one of the class's **direct** bases is
listed in `runtime-evaluated-base-classes`, or when an endpoint's decorator is
listed in `runtime-evaluated-decorators`, under `[tool.ruff.lint.flake8-type-checking]`
in `pyproject.toml`. Ruff does not follow inheritance, so every package class
that other models inherit from is listed by name.

## Adding a model base

When you add a model class that other models inherit from, add its fully
qualified name (module where it is defined, then class name) to
`runtime-evaluated-base-classes` in the same change.

If ruff reports a typing-only import in a model, do not move the import until you
have checked that the model's base is listed. Moving it for a model whose base
is missing breaks the model at runtime: Pydantic raises "not fully defined" the
first time the model is used, and SQLAlchemy fails to configure its mappers.

`tests/unit/test_runtime_evaluated_annotations.py` enforces both halves
(`api.quality.runtime-evaluated-models-resolve`): every package model base is
listed, and every Pydantic model and SQLAlchemy mapper resolves its annotations
once the package is imported.
