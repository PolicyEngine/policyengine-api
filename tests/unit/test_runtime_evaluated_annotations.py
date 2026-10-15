"""Models that read their annotations at runtime keep the imports those need.

The package's modules use ``from __future__ import annotations``, so ruff's
typing-only import rules (TC) move imports used only in annotations under
``if TYPE_CHECKING:``. Pydantic, SQLModel and SQLAlchemy read model annotations
at runtime, so ruff keeps a class's annotation imports at runtime only when one
of its direct bases is listed in ``runtime-evaluated-base-classes`` in
pyproject.toml. See docs/engineering/skills/typing-only-imports.md.
"""

from __future__ import annotations

import ast
import importlib
import pkgutil
import tomllib
from functools import cache
from pathlib import Path

import pydantic
import sqlmodel
from sqlalchemy.orm import DeclarativeBase, configure_mappers

import policyengine_api

PROJECT_ROOT = Path(__file__).parents[2]
PACKAGE_PREFIX = "policyengine_api."
# These modules assemble the Flask and ASGI apps when imported, which the route
# tests do only with patched settings. They define no classes, which
# test_skipped_app_modules_define_no_classes checks, so skipping them hides no
# model.
APP_ASSEMBLY_MODULES = frozenset({"policyengine_api.api", "policyengine_api.asgi"})
MODEL_ROOTS = (pydantic.BaseModel, sqlmodel.SQLModel, DeclarativeBase)


@cache
def _import_package_modules() -> tuple[str, ...]:
    imported = []
    for module_info in pkgutil.walk_packages(policyengine_api.__path__, PACKAGE_PREFIX):
        if module_info.name not in APP_ASSEMBLY_MODULES:
            importlib.import_module(module_info.name)
            imported.append(module_info.name)
    return tuple(imported)


def _qualified_name(model: type) -> str:
    return f"{model.__module__}.{model.__qualname__}"


def _generic_origin(model: type) -> type:
    """Return the class a Pydantic generic like ``Model[Item]`` was built from.

    Pydantic creates ``Model[Item]`` at runtime as a subclass of ``Model``. Ruff
    never sees it as a class of its own: a ``class Child(Model[Item])`` statement
    names ``Model``.
    """
    metadata = getattr(model, "__pydantic_generic_metadata__", None)
    origin = metadata.get("origin") if metadata else None
    return origin if origin is not None else model


def _package_model_classes() -> list[type]:
    _import_package_modules()
    found: set[type] = set()
    pending = list(MODEL_ROOTS)
    while pending:
        for child in pending.pop().__subclasses__():
            if child not in found:
                found.add(child)
                pending.append(child)
    return sorted(
        (
            model
            for model in found
            if model.__module__.startswith(PACKAGE_PREFIX)
            and _generic_origin(model) is model
        ),
        key=_qualified_name,
    )


def _listed_runtime_evaluated_bases() -> set[str]:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as pyproject:
        settings = tomllib.load(pyproject)
    type_checking = settings["tool"]["ruff"]["lint"]["flake8-type-checking"]
    return set(type_checking["runtime-evaluated-base-classes"])


def _unresolved_annotation(model: type[pydantic.BaseModel]) -> str | None:
    try:
        model.model_rebuild(raise_errors=True)
    except pydantic.PydanticUndefinedAnnotation as error:
        return f"{_qualified_name(model)}: {error}"
    return None


def test_every_model_base_is_listed_for_ruff() -> None:
    models = _package_model_classes()
    package_models = set(models)
    inherited_bases = {
        _generic_origin(base)
        for model in models
        for base in model.__bases__
        if _generic_origin(base) in package_models
    }
    listed = _listed_runtime_evaluated_bases()
    missing = sorted(
        _qualified_name(base)
        for base in inherited_bases
        if _qualified_name(base) not in listed
    )
    assert missing == [], (
        "these package models are inherited by other models but are missing from "
        "[tool.ruff.lint.flake8-type-checking] runtime-evaluated-base-classes in "
        "pyproject.toml, so ruff would move imports their subclasses need at "
        "runtime; add them:\n" + "\n".join(missing)
    )


def test_every_pydantic_model_resolves_its_annotations() -> None:
    unresolved = [
        message
        for model in _package_model_classes()
        if issubclass(model, pydantic.BaseModel)
        and (message := _unresolved_annotation(model)) is not None
    ]
    assert unresolved == [], (
        "these models use names in annotations that don't exist at runtime, "
        "usually an import moved under TYPE_CHECKING for a model whose base is "
        "missing from runtime-evaluated-base-classes:\n" + "\n".join(unresolved)
    )


def test_every_sqlalchemy_mapper_configures() -> None:
    _import_package_modules()
    configure_mappers()


def test_skipped_app_modules_define_no_classes() -> None:
    for module_name in sorted(APP_ASSEMBLY_MODULES):
        path = PROJECT_ROOT / f"{module_name.replace('.', '/')}.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        classes = [
            node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
        ]
        assert classes == [], (
            f"{module_name} now defines {classes}; import it in these checks, with "
            "the settings the route tests patch, so its models are checked too"
        )
