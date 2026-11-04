"""The v2-layers quality guard: every v2 route and service file has a layer.

Every ``.py`` file under ``policyengine_api/services/v2`` and
``policyengine_api/fastapi_routes/v2`` gets a layer from its file name (see
``assign_layer``), or from ``rules/v2-layer-manifest.toml`` for the few files
with other names. A file with neither fails (rule
``api.v2.files-assigned-to-layers``), so a new file is never left unchecked.

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
  ``__init__`` files (``api.v2.pure-modules-no-session-calls``) call no session
  method, SQL builder or session factory.

``database_session.py`` modules own the session's lifetime; rule
``api.v2.session-modules-no-queries`` checks them.

A method call counts as a session call when its receiver is named ``session``
or ``<something>_session`` (``session.add``, ``self._session.exec``), but not
``request.session`` (Starlette's session data), ``http_session`` or names that
only contain the word (``sessions_router``). A SQL builder counts when it was
imported from SQLAlchemy or SQLModel, or is called on a model's ``__table__``;
a session factory, when it was imported from ``policyengine_api.data.orm`` or
``policyengine_api.data.v2.database``, or is ``Session``, ``sessionmaker`` or
``create_engine`` from SQLAlchemy or SQLModel. Imports made only under
``TYPE_CHECKING`` count.

A ratcheted rule's baseline file lists its tolerated findings, one line per
occurrence, as the guard prints them. More occurrences than the baseline lists
fail, and so do fewer, so the baseline only shrinks.

The rules: docs/engineering/skills/v2-code-organization.md. Standard library
only.
"""

from __future__ import annotations

import ast
import tomllib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from scripts.rules.file_length import tracked_python_files
from scripts.rules.load import load_registry
from scripts.rules.model import Violation

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK_NAME = "v2-layers"
MANIFEST_PATH = "rules/v2-layer-manifest.toml"
SERVICES_DIRECTORY = "policyengine_api/services/v2"
ROUTES_DIRECTORY = "policyengine_api/fastapi_routes/v2"
ORGANIZATION_DOC = "docs/engineering/skills/v2-code-organization.md"

FILES_RULE = "api.v2.files-assigned-to-layers"
ROUTES_RULE = "api.v2.routes-no-sessions-or-sql"
SERVICES_RULE = "api.v2.services-no-sql"
CONNECTORS_RULE = "api.v2.connectors-never-commit"
PURE_RULE = "api.v2.pure-modules-no-session-calls"
RULES = (FILES_RULE, ROUTES_RULE, SERVICES_RULE, CONNECTORS_RULE, PURE_RULE)

SERVICE_FILE_LAYERS = {
    "services.py": "service",
    "validators.py": "validator",
    "transformations.py": "transformation",
    "types.py": "types",
    "database_session.py": "session",
}
CONNECTOR_OPERATIONS = ("creates", "reads", "updates", "deletes")
HTTP_MODEL_FILES = frozenset({"request_models.py", "response_models.py"})
# Layers the manifest may give, by directory. Connectors, session modules and
# packages get their layer from their names only.
MANIFEST_LAYERS = {
    SERVICES_DIRECTORY: frozenset(
        {"process-state", "service", "transformation", "types", "validator"}
    ),
    ROUTES_DIRECTORY: frozenset({"http-model", "http-support", "route"}),
}
PURE_LAYERS = frozenset(
    {"package", "process-state", "transformation", "types", "validator"}
)

SQL_PACKAGES = ("sqlalchemy", "sqlmodel")
DATABASE_PACKAGES = ("policyengine_api.data.orm", "policyengine_api.data.v2.database")
# What a service may import from SQLAlchemy or SQLModel: the session type, for
# annotations, and the exception classes, to raise typed failures.
SERVICE_SQL_IMPORTS = ("sqlmodel.Session", "sqlalchemy.orm.Session", "sqlalchemy.exc")
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
    {"begin", "begin_nested", "close", "commit", "rollback"}
)
DATA_ACCESS_METHODS = frozenset(
    {
        "add",
        "add_all",
        "delete",
        "exec",
        "execute",
        "flush",
        "get",
        "merge",
        "query",
        "refresh",
        "scalar",
        "scalars",
    }
)
# A database_session container's context managers.
CONTAINER_METHODS = frozenset({"read", "transaction"})
ALL_SESSION_METHODS = DATA_ACCESS_METHODS | TRANSACTION_METHODS | CONTAINER_METHODS
HTTP_PACKAGES = ("fastapi", "starlette")

FIXES = {
    FILES_RULE: (
        "name it after its layer (services.py, validators.py, transformations.py, "
        "types.py, database_session.py, "
        "database_connectors/<creates|reads|updates|deletes>[_name].py, routes.py, "
        "<name>_routes.py, request_models.py or response_models.py), or add it to "
        f"{MANIFEST_PATH} with its layer and a reason"
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


def assign_layer(path: str, manifest: Mapping[str, str]) -> str | None:
    """Return the layer of the file at ``path`` (repository-relative), or None."""
    if path in manifest:
        return manifest[path]
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
        return SERVICE_FILE_LAYERS.get(name) if resource_parts else None
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
    return "http-model" if name in HTTP_MODEL_FILES else None


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


def _is_session_receiver(node: ast.expr) -> bool:
    """Whether a method's receiver is a database session or its container."""
    if (
        isinstance(node, ast.Attribute)
        and node.attr == "session"
        and isinstance(node.value, ast.Name)
        and node.value.id == "request"
    ):
        return False
    name = _receiver_name(node).lower().lstrip("_")
    if name.startswith("http"):
        return False
    return name == "session" or name.endswith("_session")


def _calls_on_a_table(call: ast.Call) -> bool:
    """Whether a call is a SQL builder on a table, as ``Model.__table__.select()``."""
    func = call.func
    if not isinstance(func, ast.Attribute) or func.attr not in SQL_BUILDERS:
        return False
    return "__table__" in ast.unparse(func.value).split(".")


# --- policies -------------------------------------------------------------


@dataclass(frozen=True)
class LayerPolicy:
    """What one layer's rule forbids: imports, session methods and call kinds."""

    rule_id: str
    forbidden_module: Callable[[str], bool]
    session_methods: frozenset[str]
    checks_builders: bool
    checks_factories: bool
    forbidden_name: Callable[[str], bool] = _never


ROUTE_POLICY = LayerPolicy(
    ROUTES_RULE,
    _is_route_forbidden_import,
    ALL_SESSION_METHODS,
    checks_builders=True,
    checks_factories=True,
)
PURE_POLICY = LayerPolicy(
    PURE_RULE,
    _never,
    ALL_SESSION_METHODS,
    checks_builders=True,
    checks_factories=True,
)
LAYER_POLICIES = {
    "service": LayerPolicy(
        SERVICES_RULE,
        _is_http_import,
        DATA_ACCESS_METHODS,
        checks_builders=True,
        checks_factories=False,
        forbidden_name=_is_service_forbidden_sql_name,
    ),
    "connector": LayerPolicy(
        CONNECTORS_RULE,
        _is_connector_forbidden_import,
        TRANSACTION_METHODS,
        checks_builders=False,
        checks_factories=True,
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
    details = []
    from_sql = _within_any(dotted, SQL_PACKAGES)
    if policy.checks_builders and from_sql and last in SQL_BUILDERS:
        details.append(f"calls {dotted}")
    opens_a_session = _within_any(dotted, DATABASE_PACKAGES) or (
        from_sql and last in SQL_SESSION_FACTORIES
    )
    if policy.checks_factories and opens_a_session:
        details.append(f"calls {last}")
    return details


def _call_details(
    call: ast.Call, imported: Mapping[str, str], policy: LayerPolicy
) -> list[str]:
    details = []
    dotted = _dotted_name(call.func, imported)
    if dotted is not None:
        details.extend(_named_call_details(dotted, policy))
    if policy.checks_builders and _calls_on_a_table(call):
        details.append(f"calls {ast.unparse(call.func)}")
    func = call.func
    if (
        isinstance(func, ast.Attribute)
        and func.attr in policy.session_methods
        and _is_session_receiver(func.value)
    ):
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
    root: Path, manifest: Mapping[str, str], paths: Iterable[str] | None = None
) -> list[Finding]:
    """Return every finding for the v2 files under ``root``, one per occurrence."""
    findings = []
    for path in paths if paths is not None else _discovered_files(root):
        layer = assign_layer(path, manifest)
        if layer is None:
            findings.append(Finding(FILES_RULE, path, "matches no v2 layer"))
            continue
        source = (root / path).read_text(encoding="utf-8")
        findings.extend(
            Finding(rule_id, path, detail)
            for rule_id, detail in _file_findings(path, source, layer)
        )
    return sorted(findings, key=lambda finding: (finding.rule_id, str(finding)))


def _manifest_violation(message: str, fix: str) -> Violation:
    return Violation(FILES_RULE, CHECK_NAME, message, fix)


def _manifest_entry_violations(root: Path, path: str, entry: object) -> list[Violation]:
    layer = entry.get("layer") if isinstance(entry, dict) else None
    reason = entry.get("reason") if isinstance(entry, dict) else None
    directory = next(
        (folder for folder in MANIFEST_LAYERS if path.startswith(f"{folder}/")), None
    )
    if directory is None:
        return [
            _manifest_violation(
                f"{MANIFEST_PATH} lists {path}, which is not under "
                f"{SERVICES_DIRECTORY} or {ROUTES_DIRECTORY}",
                "remove the entry",
            )
        ]
    violations = []
    if not (root / path).is_file():
        violations.append(
            _manifest_violation(
                f"{MANIFEST_PATH} lists {path}, which does not exist",
                "remove the entry",
            )
        )
    elif _layer_by_name(path) is not None:
        violations.append(
            _manifest_violation(
                f"{MANIFEST_PATH} lists {path}, which its name already assigns to "
                "a layer",
                "remove the entry",
            )
        )
    if layer not in MANIFEST_LAYERS[directory]:
        violations.append(
            _manifest_violation(
                f"{MANIFEST_PATH} gives {path} the layer '{layer}', which a file "
                f"under {directory} can't have from the manifest",
                f"use one of {', '.join(sorted(MANIFEST_LAYERS[directory]))}",
            )
        )
    if not isinstance(reason, str) or not reason.strip():
        violations.append(
            _manifest_violation(
                f"{MANIFEST_PATH} gives {path} no reason",
                "say why the file has that layer",
            )
        )
    return violations


def load_manifest(root: Path) -> tuple[dict[str, str], list[Violation]]:
    """Read the manifest's file layers, and report entries that don't belong."""
    manifest_file = root / MANIFEST_PATH
    if not manifest_file.is_file():
        return {}, []
    entries = tomllib.loads(manifest_file.read_text()).get("files", {})
    manifest = {}
    violations = []
    for path, entry in sorted(entries.items()):
        layer = entry.get("layer") if isinstance(entry, dict) else None
        manifest[path] = str(layer)
        violations.extend(_manifest_entry_violations(root, path, entry))
    return manifest, violations


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
        violations.append(Violation(rule_id, CHECK_NAME, message, FIXES[rule_id]))
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
    manifest, violations = load_manifest(root)
    findings = scan(root, manifest)
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
