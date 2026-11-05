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

from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from scripts.rules.file_length import tracked_python_files
from scripts.rules.load import load_registry
from scripts.rules.model import Violation
from scripts.rules.v2_layer_checks import (
    CONNECTORS_RULE,
    EXCEPTED,
    PURE_RULE,
    ROUTES_DIRECTORY,
    ROUTES_RULE,
    SERVICES_DIRECTORY,
    SERVICES_RULE,
    SESSION_RULE,
    file_findings,
)

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable

    from scripts.rules.model import Rule, RuleException

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK_NAME = "v2-layers"
REGISTRY_FILE = "rules/registry.toml"
ORGANIZATION_DOC = "docs/engineering/skills/v2-code-organization.md"

FILES_RULE = "api.v2.files-assigned-to-layers"
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
        "services.py, validators.py, transformations.py, types.py or "
        "process_state.py in a resource package under services/v2, "
        "database_session.py directly in one, or "
        "database_connectors/<creates|reads|updates|deletes>[_name].py directly "
        "in its database_connectors package"
    ),
    ROUTES_DIRECTORY: (
        "routes.py, <name>_routes.py, <name>_models.py or <name>_support.py"
    ),
}
GLOB_CHARACTERS = frozenset("*?[")

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
            for rule_id, detail in file_findings(path, source, layer)
        )
    return sorted(findings, key=lambda finding: (finding.rule_id, str(finding)))


def _exception_violations(root: Path, exception: RuleException) -> list[Violation]:
    """Report a files-rule exception that doesn't name one unnamed v2 file.

    It must also end on an ``expires`` date and cover the whole file: the
    guard reads no ``category``, ``removal`` or ``match``.
    """
    path = exception.path

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
    if any(segment in ("", ".", "..") for segment in path.split("/")):
        # assign_layer compares paths as git ls-files writes them.
        return [
            violation(
                "but its path has a '.', '..' or empty segment, so it matches no "
                "file the guard scans",
                "write the path as git ls-files lists it",
            )
        ]
    if not (root / path).is_file():
        return [violation("but it does not exist", "remove the exception")]
    if _layer_by_name(path) is not None:
        return [
            violation("but its name already gives it a layer", "remove the exception")
        ]
    if _in_connector_package(path):
        return [
            violation(
                "but a database_connectors package holds only connector modules "
                "(rule api.v2.crud-checks-cover-every-resource also fails any "
                "other module directly in services/v2/<resource>/database_connectors)",
                f"{CONNECTOR_NAME}, {CONNECTOR_PLACE}, and remove the exception",
            )
        ]
    violations = [
        violation(
            f"but the exception sets {field}, which this rule doesn't read",
            "remove it; a files-rule exception covers the whole file and ends on "
            "its expires date",
        )
        for field in ("category", "removal", "match")
        if getattr(exception, field) is not None
    ]
    if exception.expires is None or exception.expires == date.max:
        violations.append(
            violation(
                "but the exception has no expires date",
                "give it an expires date by which the file is renamed",
            )
        )
    return violations


def file_exceptions(root: Path, rule: Rule | None) -> tuple[list[str], list[Violation]]:
    """Return the files the files rule excepts, and its exceptions that don't belong."""
    if rule is None:
        return [], []
    excepted = []
    violations = []
    for exception in rule.exceptions:
        problems = _exception_violations(root, exception)
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


# A connector gets its layer only with an operation's name, directly in a
# database_connectors package, so the fix names both.
CONNECTOR_NAME = (
    "name it after its operation, <creates|reads|updates|deletes>[_name].py"
)
CONNECTOR_PLACE = "put it directly in its database_connectors package"
CONNECTOR_NAME_FIX = (
    f"{CONNECTOR_NAME}, and {CONNECTOR_PLACE}; an exception can't stand in, "
    "because a database_connectors package holds only connector modules"
)


def _in_connector_package(path: str) -> bool:
    return path.startswith(f"{SERVICES_DIRECTORY}/") and (
        "database_connectors" in PurePosixPath(path).parts[:-1]
    )


def _fix(rule_id: str, entry: str) -> str:
    """Return the rule's fix; the files rule's names the layers of its directory."""
    if rule_id != FILES_RULE:
        return FIXES[rule_id]
    if _in_connector_package(entry.split(" ", 1)[0]):
        return CONNECTOR_NAME_FIX
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
