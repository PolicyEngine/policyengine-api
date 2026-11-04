"""The v2-layers quality guard: every v2 route and service file has a layer.

Every ``.py`` file under ``policyengine_api/services/v2`` and
``policyengine_api/fastapi_routes/v2`` gets a layer from its file name (see
``assign_layer``), or from ``rules/v2-layer-manifest.toml`` for the few files
with other names. A file with neither fails (rule
``api.v2.files-assigned-to-layers``), so a new file is never left unchecked.

Then each file's imports and calls are checked against its layer's rule:

- every file under ``fastapi_routes/v2`` (``api.v2.routes-no-sessions-or-sql``)
  imports no SQLAlchemy, SQLModel, connector, ``database_session`` or v2
  database module, and calls no SQL builder, session method or session
  factory;
- ``services.py`` modules (``api.v2.services-no-sql``) call no SQL builder and
  no data-access session method, and import no FastAPI or Starlette;
- connector modules (``api.v2.connectors-never-commit``) don't open, commit,
  roll back or close a session, or import the v2 database or a
  ``database_session`` module.

A method call counts as a session call only when its receiver's name contains
``session`` (``session.add`` or ``self._session.exec``, not ``set.add``). A SQL
builder or session factory call counts only when the name was imported from
SQLAlchemy, SQLModel or the v2 database module. Imports made only under
``TYPE_CHECKING`` count.

A ratcheted rule's baseline file lists its tolerated findings, one per line, as
the guard prints them. A finding the baseline doesn't list fails, and so does
a listed finding that no longer occurs, so the baseline only shrinks.

The rules: docs/engineering/skills/v2-code-organization.md. Standard library
only.
"""

from __future__ import annotations

import ast
import tomllib
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
RULES = (FILES_RULE, ROUTES_RULE, SERVICES_RULE, CONNECTORS_RULE)

SERVICE_FILE_LAYERS = {
    "services.py": "service",
    "validators.py": "validator",
    "transformations.py": "transformation",
    "types.py": "types",
    "database_session.py": "session",
}
CONNECTOR_OPERATIONS = ("creates", "reads", "updates", "deletes")
HTTP_MODEL_FILES = frozenset({"request_models.py", "response_models.py"})
KNOWN_LAYERS = frozenset(
    {
        *SERVICE_FILE_LAYERS.values(),
        "connector",
        "http-model",
        "http-support",
        "package",
        "process-state",
        "route",
    }
)

SQL_PACKAGES = ("sqlalchemy", "sqlmodel")
DATABASE_MODULE = "policyengine_api.data.v2.database"
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
SESSION_FACTORIES = frozenset(
    {
        "Session",
        "create_engine",
        "get_v2_read_session_factory",
        "get_v2_session_factory",
        "sessionmaker",
    }
)
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


def _module_name(path: str) -> tuple[str, bool]:
    parts = list(PurePosixPath(path).with_suffix("").parts)
    is_package = parts[-1] == "__init__"
    if is_package:
        parts = parts[:-1]
    return ".".join(parts), is_package


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
    if name == "__init__.py":
        return "package"
    if "database_connectors" not in resource_parts:
        return SERVICE_FILE_LAYERS.get(name) if resource_parts else None
    stem = name.removesuffix(".py")
    is_operation = any(
        stem == operation or stem.startswith(f"{operation}_")
        for operation in CONNECTOR_OPERATIONS
    )
    in_connector_package = resource_parts[-1] == "database_connectors"
    return "connector" if in_connector_package and is_operation else None


def _route_layer(name: str) -> str | None:
    """Assign a file under fastapi_routes/v2 by its name."""
    if name == "__init__.py":
        return "package"
    if name == "routes.py" or name.endswith("_routes.py"):
        return "route"
    return "http-model" if name in HTTP_MODEL_FILES else None


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


def _imports(tree: ast.Module, path: str) -> list[list[str]]:
    """Return, per imported module, the names that may refer to it.

    ``from package import name`` yields ``package`` and ``package.name``,
    because ``name`` may be a submodule. Relative imports are resolved, and
    imports under TYPE_CHECKING count like any other.
    """
    statements = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            statements.extend([alias.name] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            source = _from_source(node, path)
            statements.append(
                [source, *(f"{source}.{alias.name}" for alias in node.names)]
            )
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


def _forbidden_import(
    candidates: Iterable[str], is_forbidden: Callable[[str], bool]
) -> str | None:
    return next(
        (candidate for candidate in candidates if is_forbidden(candidate)), None
    )


def _is_route_forbidden_import(module: str) -> bool:
    return (
        any(_within(module, package) for package in SQL_PACKAGES)
        or _within(module, DATABASE_MODULE)
        or _is_session_or_connector_module(module)
    )


def _is_session_or_connector_module(module: str) -> bool:
    parts = module.split(".")
    return _within(module, "policyengine_api.services.v2") and (
        "database_connectors" in parts or "database_session" in parts
    )


def _is_connector_forbidden_import(module: str) -> bool:
    parts = module.split(".")
    return _within(module, DATABASE_MODULE) or (
        _within(module, "policyengine_api.services.v2") and "database_session" in parts
    )


def _is_http_import(module: str) -> bool:
    return any(_within(module, package) for package in HTTP_PACKAGES)


def _is_sql_name(dotted: str) -> bool:
    return any(_within(dotted, package) for package in SQL_PACKAGES)


@dataclass(frozen=True)
class LayerPolicy:
    """What one layer's rule forbids: imports, session methods and call kinds."""

    rule_id: str
    forbidden_import: Callable[[str], bool]
    session_methods: frozenset[str]
    checks_builders: bool
    checks_factories: bool


ROUTE_POLICY = LayerPolicy(
    ROUTES_RULE,
    _is_route_forbidden_import,
    DATA_ACCESS_METHODS | TRANSACTION_METHODS,
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
    ),
    "connector": LayerPolicy(
        CONNECTORS_RULE,
        _is_connector_forbidden_import,
        TRANSACTION_METHODS,
        checks_builders=False,
        checks_factories=True,
    ),
}


def _named_call_details(dotted: str, policy: LayerPolicy) -> list[str]:
    """Return the findings for one call to an imported name.

    For example ``calls sqlmodel.select`` or ``calls get_v2_session_factory``.
    """
    last = dotted.rsplit(".", 1)[-1]
    details = []
    if policy.checks_builders and _is_sql_name(dotted) and last in SQL_BUILDERS:
        details.append(f"calls {dotted}")
    from_database_code = _is_sql_name(dotted) or _within(
        dotted, "policyengine_api.data"
    )
    if policy.checks_factories and last in SESSION_FACTORIES and from_database_code:
        details.append(f"calls {last}")
    return details


def _session_call_detail(call: ast.Call, policy: LayerPolicy) -> str | None:
    """Return ``calls <receiver>.<method>`` for a forbidden method on a session."""
    if not isinstance(call.func, ast.Attribute):
        return None
    if call.func.attr not in policy.session_methods:
        return None
    receiver = _receiver_name(call.func.value)
    if "session" not in receiver.lower():
        return None
    return f"calls {receiver}.{call.func.attr}"


def _file_findings(path: str, source: str, layer: str) -> list[tuple[str, str]]:
    """Return (rule id, detail) for each forbidden import and call in one file."""
    policy = (
        ROUTE_POLICY
        if path.startswith(f"{ROUTES_DIRECTORY}/")
        else LAYER_POLICIES.get(layer)
    )
    if policy is None:
        return []
    tree = ast.parse(source)
    details = [
        f"imports {module}"
        for candidates in _imports(tree, path)
        if (module := _forbidden_import(candidates, policy.forbidden_import))
    ]
    imported = _imported_names(tree, path)
    for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
        dotted = _dotted_name(call.func, imported)
        if dotted is not None:
            details.extend(_named_call_details(dotted, policy))
        session_call = _session_call_detail(call, policy)
        if session_call is not None:
            details.append(session_call)
    return [(policy.rule_id, detail) for detail in details]


def _discovered_files(root: Path) -> list[str]:
    return [
        path
        for path in tracked_python_files(root)
        if path.startswith((f"{SERVICES_DIRECTORY}/", f"{ROUTES_DIRECTORY}/"))
    ]


def scan(
    root: Path, manifest: Mapping[str, str], paths: Iterable[str] | None = None
) -> list[Finding]:
    """Return every finding for the v2 files under ``root``, sorted."""
    findings = set()
    for path in paths if paths is not None else _discovered_files(root):
        layer = assign_layer(path, manifest)
        if layer is None:
            findings.add(Finding(FILES_RULE, path, "matches no v2 layer"))
            continue
        source = (root / path).read_text(encoding="utf-8")
        findings.update(
            Finding(rule_id, path, detail)
            for rule_id, detail in _file_findings(path, source, layer)
        )
    return sorted(findings, key=lambda finding: (finding.rule_id, str(finding)))


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
        if not (root / path).is_file():
            violations.append(
                Violation(
                    FILES_RULE,
                    CHECK_NAME,
                    f"{MANIFEST_PATH} lists {path}, which does not exist",
                    "remove the entry",
                )
            )
        elif _layer_by_name(path) is not None:
            violations.append(
                Violation(
                    FILES_RULE,
                    CHECK_NAME,
                    f"{MANIFEST_PATH} lists {path}, which its name already assigns "
                    "to a layer",
                    "remove the entry",
                )
            )
        if layer not in KNOWN_LAYERS:
            violations.append(
                Violation(
                    FILES_RULE,
                    CHECK_NAME,
                    f"{MANIFEST_PATH} gives {path} the unknown layer '{layer}'",
                    f"use one of {', '.join(sorted(KNOWN_LAYERS))}",
                )
            )
    return manifest, violations


def _baseline_entries(root: Path, baseline_file: str | None) -> set[str]:
    if baseline_file is None or not (root / baseline_file).is_file():
        return set()
    return {
        line.strip()
        for line in (root / baseline_file).read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


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
        tolerated = _baseline_entries(root, baseline_file)
        found = {str(finding) for finding in findings if finding.rule_id == rule_id}
        violations.extend(
            Violation(rule_id, CHECK_NAME, entry, FIXES[rule_id])
            for entry in sorted(found - tolerated)
        )
        violations.extend(
            Violation(
                rule_id,
                CHECK_NAME,
                f"baseline entry no longer applies: {entry}",
                f"remove it from {baseline_file} and lower the rule's baseline count",
            )
            for entry in sorted(tolerated - found)
        )
    return violations


def check() -> list[str]:
    """Adapter for scripts/run_quality_guards.py."""
    return [str(violation) for violation in run_check(REPO_ROOT)]
