"""The v2-layers quality guard: every v2 route and service file has a layer.

Every ``.py`` file under ``policyengine_api/services/v2`` and
``policyengine_api/fastapi_routes/v2`` gets a layer from its file name alone
(see ``assign_layer``). A file whose name gives none fails (rule
``api.v2.files-assigned-to-layers``), so a new file is never left unchecked.
A file that can't be renamed needs a ``[[rule.exception]]`` for that rule in
rules/registry.toml, ending on an ``expires`` date. The exception gives it no
layer: it gets the route checks under ``fastapi_routes/v2``, and the
pure-module (validator, transformation and types) checks under
``services/v2``.

Then each file's imports and calls are checked against its layer's rule:

- every file under ``fastapi_routes/v2`` (``api.v2.routes-no-sessions-or-sql``)
  imports no SQLAlchemy, SQLModel, connector, ``database_session``, v1 ORM or
  v2 database module, and calls no SQL builder, session method or session
  factory;
- ``services.py`` modules (``api.v2.services-no-sql``) import nothing from
  SQLAlchemy or SQLModel but the ``Session`` type and ``sqlalchemy.exc``, call
  no SQL builder or data-access session method, and import no FastAPI or
  Starlette;
- connector modules, and a ``database_connectors/__init__.py``
  (``api.v2.connectors-never-commit``), don't open, commit, roll back or close
  a session, call no session factory, and import no v1 ORM, v2 database or
  ``database_session`` module;
- validators, transformations, types, process-state modules and package
  ``__init__`` files (``api.v2.pure-modules-no-session-calls``) import nothing
  from SQLAlchemy or SQLModel but the ``Session`` type, import no connector,
  ``database_session``, v1 ORM or v2 database module, and call no session
  method, SQLAlchemy or SQLModel function or session factory.

``database_session.py`` modules, directly in a resource package, own the
session's lifetime (``api.v2.session-modules-no-data-access``): they call no
data-access session method or SQL builder and import no connector.

A method call counts as a session call when its receiver is named ``session``
or ``<something>_session`` (``session.add``, ``self._session.exec``), but not
when it is the ``.session`` of a request or websocket (Starlette's session
data), or named like an HTTP or client session (``http_session``,
``requests_session``), or only contains the word (``sessions_router``).
Routes and the pure layers may call no method on a session; services,
connectors and session modules may not call the methods listed below. A call
into SQLAlchemy or SQLModel counts, except to its exception classes; so does a
builder called on a model's ``__table__``. A session factory is any call into
``policyengine_api.data.orm`` or ``policyengine_api.data.v2.database``,
SQLAlchemy's ``Session``, ``sessionmaker`` or ``create_engine``, or an injected
``*session_factory`` (or its ``begin()``); services may open sessions, and
nothing else checked here may. Imports made only under ``TYPE_CHECKING``
count. Not recognised: a session bound to another name, an alias of a model's
table, and a name re-exported through another module.

A ratcheted rule's baseline file lists its tolerated findings, one line per
occurrence, as the guard prints them. More occurrences than the baseline lists
fail, and so do fewer, so the baseline only shrinks.

The rules: docs/engineering/skills/v2-code-organization.md. Standard library
only.
"""

from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from scripts.rules.file_length import tracked_python_files
from scripts.rules.load import load_registry
from scripts.rules.model import Violation

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Mapping

    from scripts.rules.model import Rule

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK_NAME = "v2-layers"
REGISTRY_FILE = "rules/registry.toml"
SERVICES_DIRECTORY = "policyengine_api/services/v2"
ROUTES_DIRECTORY = "policyengine_api/fastapi_routes/v2"
ORGANIZATION_DOC = "docs/engineering/skills/v2-code-organization.md"

FILES_RULE = "api.v2.files-assigned-to-layers"
ROUTES_RULE = "api.v2.routes-no-sessions-or-sql"
SERVICES_RULE = "api.v2.services-no-sql"
CONNECTORS_RULE = "api.v2.connectors-never-commit"
PURE_RULE = "api.v2.pure-modules-no-session-calls"
SESSION_RULE = "api.v2.session-modules-no-data-access"
RULES = (
    FILES_RULE,
    ROUTES_RULE,
    SERVICES_RULE,
    CONNECTORS_RULE,
    PURE_RULE,
    SESSION_RULE,
)

SERVICE_FILE_LAYERS = {
    "services.py": "service",
    "validators.py": "validator",
    "transformations.py": "transformation",
    "types.py": "types",
    "process_state.py": "process-state",
    "database_session.py": "session",
}
CONNECTOR_OPERATIONS = ("creates", "reads", "updates", "deletes")
# The names that give a layer, by directory, for the files rule's fix message.
LAYER_NAMES = {
    SERVICES_DIRECTORY: (
        "services.py, validators.py, transformations.py, types.py, "
        "process_state.py, database_session.py or "
        "database_connectors/<creates|reads|updates|deletes>[_name].py"
    ),
    ROUTES_DIRECTORY: (
        "routes.py, <name>_routes.py, <name>_models.py or <name>_support.py"
    ),
}
# What a [[rule.exception]] for the files rule makes a file: no layer of its
# own; under services/v2 it gets the pure-module checks (under
# fastapi_routes/v2 every file gets the route checks).
EXCEPTED = "excepted"
PURE_LAYERS = frozenset(
    {EXCEPTED, "package", "process-state", "transformation", "types", "validator"}
)
GLOB_CHARACTERS = frozenset("*?[")

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

FIXES = {
    FILES_RULE: (
        "name it after its layer ({names}), or, if it can't be renamed, add a "
        f"[[rule.exception]] for {FILES_RULE} to {REGISTRY_FILE} with its path, "
        "a reason and an expires date"
    ),
    ROUTES_RULE: (
        "v2 route modules call one service method and map its typed failures to "
        "HTTP; move session and SQL work into the service and its connectors "
        f"({ORGANIZATION_DOC})"
    ),
    SERVICES_RULE: (
        "services sequence work: build and run SQL in a connector, pass it the "
        f"session, and define HTTP models under fastapi_routes/v2 ({ORGANIZATION_DOC})"
    ),
    CONNECTORS_RULE: (
        "connectors use the session the service passes them; the service's "
        "database_session container opens, commits, rolls back and closes it "
        f"({ORGANIZATION_DOC})"
    ),
    PURE_RULE: (
        "validators, transformations and types work on values and loaded rows; "
        "load them in a connector and pass them in from the service "
        f"({ORGANIZATION_DOC})"
    ),
    SESSION_RULE: (
        "a database_session module only opens, commits, rolls back and closes "
        f"sessions; read and write rows in a connector ({ORGANIZATION_DOC})"
    ),
}


@dataclass(frozen=True)
class Finding:
    """One import or call a layer's rule forbids, or a file with no layer."""

    rule_id: str
    path: str
    detail: str

    def __str__(self) -> str:
        """Format as the baseline lists it: ``<path> <detail>``."""
        return f"{self.path} {self.detail}"


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


# --- layers ---------------------------------------------------------------


def assign_layer(path: str, exceptions: Collection[str] = ()) -> str | None:
    """Return the layer of the file at ``path`` (repository-relative), or None.

    A path in ``exceptions`` is ``excepted``: under services/v2 it gets the
    pure-module checks, and under fastapi_routes/v2 the route checks.
    """
    if path in exceptions:
        return EXCEPTED
    return _layer_by_name(path)


def _layer_by_name(path: str) -> str | None:
    if path.startswith(f"{SERVICES_DIRECTORY}/"):
        return _service_layer(PurePosixPath(path).parts)
    if path.startswith(f"{ROUTES_DIRECTORY}/"):
        return _route_layer(PurePosixPath(path).name)
    return None


def _service_layer(parts: tuple[str, ...]) -> str | None:
    """Assign a file under services/v2 by name, given its path parts."""
    name = parts[-1]
    resource_parts = parts[3:-1]
    in_connector_package = bool(resource_parts) and (
        resource_parts[-1] == "database_connectors"
    )
    if name == "__init__.py":
        return "connector" if in_connector_package else "package"
    if "database_connectors" not in resource_parts:
        layer = SERVICE_FILE_LAYERS.get(name) if resource_parts else None
        # A session module sits directly in its resource package, where the
        # session-module rule looks for it.
        return None if layer == "session" and len(resource_parts) > 1 else layer
    stem = name.removesuffix(".py")
    is_operation = any(
        stem == operation or stem.startswith(f"{operation}_")
        for operation in CONNECTOR_OPERATIONS
    )
    return "connector" if in_connector_package and is_operation else None


def _route_layer(name: str) -> str | None:
    """Assign a file under fastapi_routes/v2 by its name."""
    if name == "__init__.py":
        return "package"
    if name == "routes.py" or name.endswith("_routes.py"):
        return "route"
    if name.endswith("_models.py"):
        return "http-model"
    return "http-support" if name.endswith("_support.py") else None


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


def _file_findings(path: str, source: str, layer: str) -> list[tuple[str, str]]:
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


# --- scanning and comparing -----------------------------------------------


def _discovered_files(root: Path) -> list[str]:
    return [
        path
        for path in tracked_python_files(root)
        if path.startswith((f"{SERVICES_DIRECTORY}/", f"{ROUTES_DIRECTORY}/"))
    ]


def scan(
    root: Path, exceptions: Collection[str] = (), paths: Iterable[str] | None = None
) -> list[Finding]:
    """Return every finding for the v2 files under ``root``, one per occurrence."""
    findings = []
    for path in paths if paths is not None else _discovered_files(root):
        layer = assign_layer(path, exceptions)
        if layer is None:
            findings.append(Finding(FILES_RULE, path, "matches no v2 layer"))
            continue
        source = (root / path).read_text(encoding="utf-8")
        findings.extend(
            Finding(rule_id, path, detail)
            for rule_id, detail in _file_findings(path, source, layer)
        )
    return sorted(findings, key=lambda finding: (finding.rule_id, str(finding)))


def _exception_violations(root: Path, path: str) -> list[Violation]:
    """Report a files-rule exception that names no unnamed v2 file."""

    def violation(problem: str, fix: str) -> Violation:
        return Violation(
            FILES_RULE,
            CHECK_NAME,
            f"{REGISTRY_FILE} excepts {path} from {FILES_RULE}, {problem}",
            fix,
        )

    in_v2 = path.startswith((f"{SERVICES_DIRECTORY}/", f"{ROUTES_DIRECTORY}/"))
    if not in_v2 or GLOB_CHARACTERS & set(path) or not path.endswith(".py"):
        return [
            violation(
                f"which is not one file under {SERVICES_DIRECTORY} or "
                f"{ROUTES_DIRECTORY}",
                "name one file there, or remove the exception",
            )
        ]
    if not (root / path).is_file():
        return [violation("but it does not exist", "remove the exception")]
    if _layer_by_name(path) is not None:
        return [
            violation("but its name already gives it a layer", "remove the exception")
        ]
    return []


def file_exceptions(root: Path, rule: Rule | None) -> tuple[list[str], list[Violation]]:
    """Return the files the files rule excepts, and its exceptions that don't belong."""
    if rule is None:
        return [], []
    excepted = []
    violations = []
    for exception in rule.exceptions:
        problems = _exception_violations(root, exception.path)
        violations += problems
        if not problems:
            excepted.append(exception.path)
    return excepted, violations


def _baseline_entries(root: Path, baseline_file: str | None) -> Counter[str]:
    if baseline_file is None or not (root / baseline_file).is_file():
        return Counter()
    return Counter(
        line.strip()
        for line in (root / baseline_file).read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def _occurrences(count: int) -> str:
    return f"{count} occurrence" if count == 1 else f"{count} occurrences"


def _fix(rule_id: str, entry: str) -> str:
    """Return the rule's fix; the files rule's names the layers of its directory."""
    if rule_id != FILES_RULE:
        return FIXES[rule_id]
    directory = (
        SERVICES_DIRECTORY if entry.startswith(SERVICES_DIRECTORY) else ROUTES_DIRECTORY
    )
    return FIXES[FILES_RULE].format(names=LAYER_NAMES[directory])


def _compare(
    rule_id: str,
    found: Counter[str],
    tolerated: Counter[str],
    baseline_file: str | None,
) -> list[Violation]:
    """Report findings beyond the baseline, and baseline entries beyond the findings."""
    violations = []
    for entry in sorted(found):
        if found[entry] <= tolerated[entry]:
            continue
        message = (
            entry
            if not tolerated[entry]
            else f"{entry} ({_occurrences(found[entry])}, the baseline tolerates "
            f"{tolerated[entry]})"
        )
        violations.append(Violation(rule_id, CHECK_NAME, message, _fix(rule_id, entry)))
    for entry in sorted(tolerated):
        if tolerated[entry] <= found[entry]:
            continue
        detail = (
            entry
            if not found[entry]
            else f"{entry} ({_occurrences(found[entry])}, the baseline lists "
            f"{tolerated[entry]})"
        )
        violations.append(
            Violation(
                rule_id,
                CHECK_NAME,
                f"baseline entry no longer applies: {detail}",
                f"remove it from {baseline_file} and lower the rule's baseline count",
            )
        )
    return violations


def run_check(root: Path = REPO_ROOT) -> list[Violation]:
    """Scan the v2 files under ``root`` and compare with each rule's baseline."""
    registry, violations = load_registry(root)
    if registry is None:
        return violations
    excepted, violations = file_exceptions(root, registry.rule(FILES_RULE))
    findings = scan(root, excepted)
    for rule_id in RULES:
        rule = registry.rule(rule_id)
        baseline_file = rule.baseline.file if rule and rule.baseline else None
        found = Counter(
            str(finding) for finding in findings if finding.rule_id == rule_id
        )
        violations += _compare(
            rule_id, found, _baseline_entries(root, baseline_file), baseline_file
        )
    return violations


def check() -> list[str]:
    """Adapter for scripts/run_quality_guards.py."""
    return [str(violation) for violation in run_check(REPO_ROOT)]
