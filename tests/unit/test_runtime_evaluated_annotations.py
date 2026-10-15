"""Models that read their annotations at runtime keep the imports those need.

The package's modules use ``from __future__ import annotations``, so ruff's
typing-only import rules (TC) move imports used only in annotations under
``if TYPE_CHECKING:``. Pydantic, SQLModel and SQLAlchemy read model annotations
at runtime, so ruff keeps a class's annotation imports at runtime only when it
treats the class as runtime-evaluated: one of its bases resolves, through the
import in the class's own module, to a name listed in
``runtime-evaluated-base-classes`` in pyproject.toml, or is a class in the same
module that is itself runtime-evaluated. Ruff does not follow re-exports. See
docs/engineering/skills/typing-only-imports.md.
"""

from __future__ import annotations

import ast
import importlib
import pkgutil
import sys
import tomllib
from dataclasses import dataclass
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

# A module that exercises each way a base can resolve, for
# test_base_resolution_matches_ruff.
EXAMPLE_MODULE = """\
import pydantic
from typing import Generic, TypeVar
from policyengine_api.models import Listed
from policyengine_api.reexports import Listed as ReexportedListed
from pydantic_settings import BaseSettings
from .siblings import Sibling
class ViaImport(Listed): ...
class ViaModuleAttribute(pydantic.BaseModel): ...
class LocalBase(Listed): ...
class ViaSameModuleChain(LocalBase): ...
class ViaGeneric(Listed, Generic[TypeVar("T")]): ...
class ViaReexport(ReexportedListed): ...
class ViaUnlistedThirdParty(BaseSettings): ...
class ViaRelativeImport(Sibling): ...
"""


@dataclass(frozen=True)
class ModuleSource:
    """A module's top-level classes and the qualified names its imports bind."""

    name: str
    classes: dict[str, ast.ClassDef]
    imported_names: dict[str, str]


def _parse_module_source(name: str, text: str, *, is_package: bool) -> ModuleSource:
    tree = ast.parse(text)
    package = name if is_package else name.rpartition(".")[0]
    imported_names: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                anchor = (
                    package.rsplit(".", node.level - 1)[0]
                    if node.level > 1
                    else package
                )
                module = f"{anchor}.{node.module}" if node.module else anchor
            else:
                module = node.module or ""
            for alias in node.names:
                imported_names[alias.asname or alias.name] = f"{module}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    imported_names[alias.asname] = alias.name
                else:
                    top_level = alias.name.split(".")[0]
                    imported_names[top_level] = top_level
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    return ModuleSource(name=name, classes=classes, imported_names=imported_names)


@cache
def _module_source(module_name: str) -> ModuleSource:
    path = Path(sys.modules[module_name].__file__)
    return _parse_module_source(
        module_name,
        path.read_text(encoding="utf-8"),
        is_package=path.name == "__init__.py",
    )


def _qualified_base_name(source: ModuleSource, base: ast.expr) -> str | None:
    """Resolve a base expression the way ruff does: through the module's imports."""
    if isinstance(base, ast.Subscript):
        base = base.value
    attributes = []
    while isinstance(base, ast.Attribute):
        attributes.append(base.attr)
        base = base.value
    if not isinstance(base, ast.Name):
        return None
    if base.id in source.imported_names:
        head = source.imported_names[base.id]
    elif base.id in source.classes:
        head = f"{source.name}.{base.id}"
    else:
        head = base.id
    return ".".join([head, *reversed(attributes)])


def _is_runtime_evaluated(
    source: ModuleSource,
    class_node: ast.ClassDef,
    listed: frozenset[str],
    visiting: frozenset[str] = frozenset(),
) -> bool:
    """Return whether ruff treats the class's annotations as read at runtime."""
    for base in class_node.bases:
        base_name = _qualified_base_name(source, base)
        if base_name in listed:
            return True
        local_name = (base_name or "").removeprefix(f"{source.name}.")
        if (
            local_name in source.classes
            and local_name not in visiting
            and _is_runtime_evaluated(
                source,
                source.classes[local_name],
                listed,
                visiting | {class_node.name},
            )
        ):
            return True
    return False


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
    never sees it as a class of its own.
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


@cache
def _listed_runtime_evaluated_bases() -> frozenset[str]:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as pyproject:
        settings = tomllib.load(pyproject)
    type_checking = settings["tool"]["ruff"]["lint"]["flake8-type-checking"]
    return frozenset(type_checking["runtime-evaluated-base-classes"])


def _not_runtime_evaluated(model: type) -> str | None:
    """Describe a top-level model ruff would not treat as runtime-evaluated."""
    source = _module_source(model.__module__)
    class_node = source.classes.get(model.__qualname__)
    if class_node is None or _is_runtime_evaluated(
        source, class_node, _listed_runtime_evaluated_bases()
    ):
        return None
    bases = [_qualified_base_name(source, base) for base in class_node.bases]
    return f"{_qualified_name(model)}: bases as ruff resolves them: {bases}"


def _unresolved_annotation(model: type[pydantic.BaseModel]) -> str | None:
    try:
        model.model_rebuild(raise_errors=True)
    except pydantic.PydanticUndefinedAnnotation as error:
        return f"{_qualified_name(model)}: {error}"
    return None


def test_every_model_base_is_listed_for_ruff() -> None:
    unlisted = [
        message
        for model in _package_model_classes()
        if (message := _not_runtime_evaluated(model)) is not None
    ]
    assert unlisted == [], (
        "ruff would not treat these models' annotations as read at runtime, so it "
        "would ask for imports they need to be moved under TYPE_CHECKING. Add the "
        "base path ruff resolves (the path the module imports it from) to "
        "[tool.ruff.lint.flake8-type-checking] runtime-evaluated-base-classes in "
        "pyproject.toml:\n" + "\n".join(unlisted)
    )


def test_base_resolution_matches_ruff() -> None:
    source = _parse_module_source(
        "policyengine_api.example", EXAMPLE_MODULE, is_package=False
    )
    listed = frozenset(
        {
            "policyengine_api.models.Listed",
            "pydantic.BaseModel",
            "policyengine_api.siblings.Sibling",
        }
    )
    runtime_evaluated = {
        name
        for name, class_node in source.classes.items()
        if _is_runtime_evaluated(source, class_node, listed)
    }

    assert runtime_evaluated == {
        "ViaImport",
        "ViaModuleAttribute",
        "LocalBase",
        "ViaSameModuleChain",
        "ViaGeneric",
        "ViaRelativeImport",
    }


def test_every_pydantic_model_resolves_its_annotations() -> None:
    unresolved = [
        message
        for model in _package_model_classes()
        if issubclass(model, pydantic.BaseModel)
        and (message := _unresolved_annotation(model)) is not None
    ]
    assert unresolved == [], (
        "these models use names in annotations that don't exist at runtime, "
        "usually an import moved under TYPE_CHECKING for a model ruff doesn't treat "
        "as runtime-evaluated:\n" + "\n".join(unresolved)
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
