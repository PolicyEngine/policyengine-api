"""Import and call checks for the v2-layers quality guard, one layer at a time.

``file_findings`` parses one v2 file and returns what its layer's rule
forbids in it. scripts/rules/v2_layers.py assigns the layers, runs these
checks over every v2 file and compares the findings with the baselines; its
docstring describes what each layer may import and call.

Standard library only.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

SERVICES_DIRECTORY = "policyengine_api/services/v2"
ROUTES_DIRECTORY = "policyengine_api/fastapi_routes/v2"

ROUTES_RULE = "api.v2.routes-no-sessions-or-sql"
SERVICES_RULE = "api.v2.services-no-sql"
CONNECTORS_RULE = "api.v2.connectors-never-commit"
PURE_RULE = "api.v2.pure-modules-no-session-calls"
SESSION_RULE = "api.v2.session-modules-no-data-access"

# What a [[rule.exception]] for the files rule makes a file: no layer of its
# own; under services/v2 it gets the pure-module checks (under
# fastapi_routes/v2 every file gets the route checks).
EXCEPTED = "excepted"
PURE_LAYERS = frozenset(
    {EXCEPTED, "package", "process-state", "transformation", "types", "validator"}
)

SQL_PACKAGES = ("sqlalchemy", "sqlmodel")
DATABASE_PACKAGES = ("policyengine_api.data.orm", "policyengine_api.data.v2.database")
SESSION_TYPES = ("sqlmodel.Session", "sqlalchemy.orm.Session")
SQL_EXCEPTIONS = "sqlalchemy.exc"
# What a service may import from SQLAlchemy or SQLModel: the session type, for
# annotations, and the exception classes, to raise typed failures.
SERVICE_SQL_IMPORTS = (*SESSION_TYPES, SQL_EXCEPTIONS)
SQL_BUILDERS = frozenset(
    {
        "delete",
        "except_",
        "exists",
        "insert",
        "intersect",
        "literal_column",
        "select",
        "text",
        "union",
        "union_all",
        "update",
        "values",
    }
)
SQL_SESSION_FACTORIES = frozenset({"Session", "create_engine", "sessionmaker"})
TRANSACTION_METHODS = frozenset(
    {"begin", "begin_nested", "close", "commit", "invalidate", "reset", "rollback"}
)
DATA_ACCESS_METHODS = frozenset(
    {
        "add",
        "add_all",
        "bulk_insert_mappings",
        "bulk_save_objects",
        "bulk_update_mappings",
        "connection",
        "delete",
        "exec",
        "execute",
        "expunge",
        "expunge_all",
        "flush",
        "get",
        "get_one",
        "merge",
        "query",
        "refresh",
        "scalar",
        "scalars",
    }
)
# A database_session container's context managers, which open a session.
CONTAINER_METHODS = frozenset({"read", "transaction"})
# Receiver name prefixes, before "_session", of web rather than database sessions.
WEB_SESSION_WORDS = ("client", "http", "requests")
# Owners whose ``.session`` is Starlette's session data, not a database session.
REQUEST_OWNERS = frozenset({"req", "request", "websocket", "ws"})
HTTP_PACKAGES = ("fastapi", "starlette")


def _within(module: str, package: str) -> bool:
    return module == package or module.startswith(f"{package}.")


def _within_any(module: str, packages: Iterable[str]) -> bool:
    return any(_within(module, package) for package in packages)


def _module_name(path: str) -> tuple[str, bool]:
    parts = list(PurePosixPath(path).with_suffix("").parts)
    is_package = parts[-1] == "__init__"
    if is_package:
        parts = parts[:-1]
    return ".".join(parts), is_package


# --- imports --------------------------------------------------------------


def _from_source(node: ast.ImportFrom, path: str) -> str:
    """Return the absolute module a ``from ... import`` reads from."""
    if not node.level:
        return node.module or ""
    module_name, is_package = _module_name(path)
    base = module_name.split(".")
    if not is_package:
        base = base[:-1]
    if node.level > 1:
        base = base[: -(node.level - 1)]
    return ".".join([*base, *([node.module] if node.module else [])])


@dataclass(frozen=True)
class ImportStatement:
    """One imported module, or one ``from`` import with the names it binds."""

    module: str
    names: tuple[str, ...]


def _imports(tree: ast.Module, path: str) -> list[ImportStatement]:
    """Return every import in a module; relative imports are resolved.

    Imports under TYPE_CHECKING and inside functions count like any other.
    """
    statements = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            statements.extend(ImportStatement(alias.name, ()) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            source = _from_source(node, path)
            names = tuple(f"{source}.{alias.name}" for alias in node.names)
            statements.append(ImportStatement(source, names))
    return statements


def _imported_names(tree: ast.Module, path: str) -> dict[str, str]:
    """Map each name a module binds by importing to the dotted name it refers to."""
    names = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[0]
                names[bound] = alias.name if alias.asname else bound
        elif isinstance(node, ast.ImportFrom):
            source = _from_source(node, path)
            for alias in node.names:
                names[alias.asname or alias.name] = f"{source}.{alias.name}"
    return names


def _is_session_or_connector_module(module: str) -> bool:
    parts = module.split(".")
    return _within(module, "policyengine_api.services.v2") and (
        "database_connectors" in parts or "database_session" in parts
    )


def _is_route_forbidden_import(module: str) -> bool:
    return (
        _within_any(module, SQL_PACKAGES)
        or _within_any(module, DATABASE_PACKAGES)
        or _is_session_or_connector_module(module)
    )


def _is_connector_module(module: str) -> bool:
    return _within(module, "policyengine_api.services.v2") and (
        "database_connectors" in module.split(".")
    )


def _is_connector_forbidden_import(module: str) -> bool:
    parts = module.split(".")
    return _within_any(module, DATABASE_PACKAGES) or (
        _within(module, "policyengine_api.services.v2") and "database_session" in parts
    )


def _is_http_import(module: str) -> bool:
    return _within_any(module, HTTP_PACKAGES)


def _is_service_forbidden_sql_name(name: str) -> bool:
    return _within_any(name, SQL_PACKAGES) and not _within_any(
        name, SERVICE_SQL_IMPORTS
    )


def _is_pure_forbidden_import(module: str) -> bool:
    return _within_any(module, DATABASE_PACKAGES) or _is_session_or_connector_module(
        module
    )


def _is_pure_forbidden_sql_name(name: str) -> bool:
    return _within_any(name, SQL_PACKAGES) and not _within_any(name, SESSION_TYPES)


def _never(_module: str) -> bool:
    return False


# --- calls ----------------------------------------------------------------


def _dotted_name(node: ast.expr, imported: Mapping[str, str]) -> str | None:
    """Resolve a called name such as ``select`` or ``sa.text`` through the imports."""
    attributes = []
    while isinstance(node, ast.Attribute):
        attributes.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name) or node.id not in imported:
        return None
    return ".".join([imported[node.id], *reversed(attributes)])


def _receiver_name(node: ast.expr) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _is_request_owner(node: ast.expr) -> bool:
    name = _receiver_name(node).lower().lstrip("_")
    return name in REQUEST_OWNERS or name.endswith("_request")


def _is_session_receiver(node: ast.expr) -> bool:
    """Whether a method's receiver is a database session or its container."""
    if (
        isinstance(node, ast.Attribute)
        and node.attr == "session"
        and _is_request_owner(node.value)
    ):
        return False
    name = _receiver_name(node).lower().lstrip("_")
    if name == "session":
        return True
    prefix = name.removesuffix("_session")
    return prefix != name and not any(word in prefix for word in WEB_SESSION_WORDS)


def _is_session_factory_name(name: str) -> bool:
    return name.lower().lstrip("_").endswith("session_factory")


def _injected_factory_detail(call: ast.Call) -> str | None:
    """Return ``calls <factory>`` when a call opens a session from an injected factory.

    ``session_factory()``, ``self._session_factory()`` and
    ``session_factory.begin()`` count.
    """
    func = call.func
    if _is_session_factory_name(_receiver_name(func)):
        return f"calls {_receiver_name(func)}"
    if (
        isinstance(func, ast.Attribute)
        and func.attr == "begin"
        and _is_session_factory_name(_receiver_name(func.value))
    ):
        return f"calls {_receiver_name(func.value)}.begin"
    return None


def _calls_on_a_table(call: ast.Call) -> bool:
    """Whether a call is a SQL builder on a table, as ``Model.__table__.insert()``."""
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr in SQL_BUILDERS - {"values"}
        and isinstance(func.value, ast.Attribute)
        and func.value.attr == "__table__"
    )


# --- policies -------------------------------------------------------------


@dataclass(frozen=True)
class LayerPolicy:
    """What one layer's rule forbids: imports, session methods and call kinds.

    ``session_methods`` of None forbids every method on a session.
    ``checks_sql_calls`` forbids every call into SQLAlchemy or SQLModel but
    its exception classes; ``checks_builders`` only its SQL builders. Either
    also forbids builders called on a model's ``__table__``.
    ``checks_factories`` forbids opening a session from a session factory.
    """

    rule_id: str
    forbidden_module: Callable[[str], bool]
    session_methods: frozenset[str] | None
    checks_sql_calls: bool
    checks_factories: bool
    forbidden_name: Callable[[str], bool] = _never
    checks_builders: bool = False


ROUTE_POLICY = LayerPolicy(
    ROUTES_RULE,
    _is_route_forbidden_import,
    None,
    checks_sql_calls=True,
    checks_factories=True,
)
PURE_POLICY = LayerPolicy(
    PURE_RULE,
    _is_pure_forbidden_import,
    None,
    checks_sql_calls=True,
    checks_factories=True,
    forbidden_name=_is_pure_forbidden_sql_name,
)
LAYER_POLICIES = {
    "service": LayerPolicy(
        SERVICES_RULE,
        _is_http_import,
        DATA_ACCESS_METHODS,
        checks_sql_calls=True,
        checks_factories=False,
        forbidden_name=_is_service_forbidden_sql_name,
    ),
    "connector": LayerPolicy(
        CONNECTORS_RULE,
        _is_connector_forbidden_import,
        TRANSACTION_METHODS | CONTAINER_METHODS,
        checks_sql_calls=False,
        checks_factories=True,
    ),
    "session": LayerPolicy(
        SESSION_RULE,
        _is_connector_module,
        DATA_ACCESS_METHODS,
        checks_sql_calls=False,
        checks_factories=False,
        checks_builders=True,
    ),
    **dict.fromkeys(PURE_LAYERS, PURE_POLICY),
}


def _policy(path: str, layer: str) -> LayerPolicy | None:
    if path.startswith(f"{ROUTES_DIRECTORY}/"):
        return ROUTE_POLICY
    return LAYER_POLICIES.get(layer)


def _import_details(statement: ImportStatement, policy: LayerPolicy) -> list[str]:
    """Return ``imports <module>`` for each module or name the policy forbids."""
    if policy.forbidden_module(statement.module):
        return [f"imports {statement.module}"]
    module_level = next(
        (name for name in statement.names if policy.forbidden_module(name)), None
    )
    if module_level is not None:
        return [f"imports {module_level}"]
    if not statement.names:
        forbidden = policy.forbidden_name(statement.module)
        return [f"imports {statement.module}"] if forbidden else []
    return [
        f"imports {name}" for name in statement.names if policy.forbidden_name(name)
    ]


def _named_call_details(dotted: str, policy: LayerPolicy) -> list[str]:
    """Return the findings for one call to an imported name.

    For example ``calls sqlmodel.select`` or ``calls get_v2_session_factory``.
    """
    last = dotted.rsplit(".", 1)[-1]
    from_sql = _within_any(dotted, SQL_PACKAGES)
    opens_a_session = _within_any(dotted, DATABASE_PACKAGES) or (
        from_sql and last in SQL_SESSION_FACTORIES
    )
    if opens_a_session:
        return [f"calls {last}"] if policy.checks_factories else []
    if policy.checks_sql_calls and from_sql and not _within(dotted, SQL_EXCEPTIONS):
        return [f"calls {dotted}"]
    if policy.checks_builders and from_sql and last in SQL_BUILDERS:
        return [f"calls {dotted}"]
    return []


def _call_details(
    call: ast.Call, imported: Mapping[str, str], policy: LayerPolicy
) -> list[str]:
    details = []
    dotted = _dotted_name(call.func, imported)
    if dotted is not None:
        details.extend(_named_call_details(dotted, policy))
    if (policy.checks_sql_calls or policy.checks_builders) and _calls_on_a_table(call):
        details.append(f"calls {ast.unparse(call.func)}")
    factory = _injected_factory_detail(call) if policy.checks_factories else None
    if factory is not None:
        details.append(factory)
    func = call.func
    forbidden_method = isinstance(func, ast.Attribute) and (
        policy.session_methods is None or func.attr in policy.session_methods
    )
    if forbidden_method and _is_session_receiver(func.value):
        details.append(f"calls {_receiver_name(func.value)}.{func.attr}")
    return details


def file_findings(path: str, source: str, layer: str) -> list[tuple[str, str]]:
    """Return (rule id, detail) for each forbidden import and call in one file."""
    policy = _policy(path, layer)
    if policy is None:
        return []
    tree = ast.parse(source)
    details = [
        detail
        for statement in _imports(tree, path)
        for detail in _import_details(statement, policy)
    ]
    imported = _imported_names(tree, path)
    for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
        details.extend(_call_details(call, imported, policy))
    return [(policy.rule_id, detail) for detail in details]
