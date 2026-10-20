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
annotation imports at runtime only when it treats the class as runtime-evaluated,
or when an endpoint's decorator is listed in `runtime-evaluated-decorators`, under
`[tool.ruff.lint.flake8-type-checking]` in `pyproject.toml`. A class is
runtime-evaluated when one of its bases:

- resolves, through the import in the class's own module, to a name listed in
  `runtime-evaluated-base-classes`; or
- is a class defined in the same module that is itself runtime-evaluated.

Ruff matches the path the module imports the base from, not where the base is
defined. A listed base imported through a re-export (`from package import Base`,
where `package/__init__.py` re-exports it) does not match its listed definition
path. Ruff does not follow inheritance across modules, so every package class
that models in other modules inherit from is listed.

### Route modules with per-router dependencies

FastAPI resolves an endpoint's string annotations against its module's globals
only. A route that declares a dependency with `Annotated` therefore needs every
name in that annotation at module level. Query dependencies are module-level
aliases, such as `CountryQueryDependency`. The signed-in user routes also depend
on `require_user`, the authenticator `NativeRouteDependencies` injects into each
router, which exists only inside the router builder. Their modules
(`fastapi_routes/v2/me`, `user_households`, `user_policies`, `user_reports` and
`user_simulations`) don't use `from __future__ import annotations`, so
`Annotated[AccountPrincipal, Depends(require_user)]` is evaluated where the
handler is defined, and the names their other annotations use are imported at
runtime. With the future import, FastAPI would silently treat `principal` as a
required query parameter.

## Adding a model base

When you add a model class that models in other modules inherit from, add the
qualified name those modules import it by (normally the module where it is
defined, then the class name) to `runtime-evaluated-base-classes` in the same
change. Import model bases from the module that defines them, so one listed path
covers every subclass.

If ruff reports a typing-only import in a model, do not move the import until you
have checked that the model's base is listed. Moving it for a model whose base
is missing breaks the model at runtime: Pydantic raises "not fully defined" the
first time the model is used, and SQLAlchemy fails to configure its mappers.

`tests/unit/test_runtime_evaluated_annotations.py` enforces both halves
(`api.quality.runtime-evaluated-models-resolve`): every package model is one ruff
treats as runtime-evaluated, resolving its bases the way ruff does, and every
Pydantic model and SQLAlchemy mapper resolves its annotations once the package is
imported.
