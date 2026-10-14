"""Weighted-microdata guards: weights aren't values.

Microdata columns come in four kinds (weights, values, labels and counts), and
each allows different operations; docs/engineering/skills/microdata-weights.md
sets them out. These checks read the source, so they recognise a weight by its
name: a string or f-string ending in ``_weight`` or ``_weights``, a name
assigned from one, or a ``.weights`` attribute. They don't follow data through
function calls or containers.
"""

from __future__ import annotations

import ast
import enum
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[3]
PACKAGE_ROOT = PROJECT_ROOT / "policyengine_api"
FIXTURES_ROOT = PROJECT_ROOT / "rules" / "fixtures"

WEIGHT_SUFFIXES = ("_weight", "_weights")
# Reductions that a weighted MicroSeries or MicroDataFrame column weights.
WEIGHTED_REDUCTIONS = frozenset(
    {"sum", "mean", "median", "quantile", "std", "count", "groupby", "cumsum"}
)
# Weighted aggregators, with the position and keyword of the argument each one
# aggregates as a value.
WEIGHTED_AGGREGATORS: dict[str, tuple[int | None, str]] = {
    "Aggregate": (None, "variable"),
    "ChangeAggregate": (None, "variable"),
    # The Simulation API's output helpers. The Public API has none, but the
    # rule's proof is the real Simulation API line that #767 fixed.
    "_sum_output_variable": (1, "variable"),
    "_change_output_variable": (2, "variable"),
}
# Calls and attributes that return a weighted column's or frame's raw values.
STRIPPING_FUNCTIONS = frozenset(
    {
        "np.array",
        "np.asarray",
        "numpy.array",
        "numpy.asarray",
        "pd.DataFrame",
        "pd.Series",
        "pandas.DataFrame",
        "pandas.Series",
    }
)
STRIPPING_METHODS = frozenset({"to_numpy", "tolist"})
STRIPPING_ATTRIBUTES = frozenset({"values"})
# Methods whose result is weighted exactly as their receiver is.
WEIGHTING_PRESERVING_METHODS = frozenset(
    {"abs", "astype", "clip", "copy", "fillna", "round"}
)
# policyengine's economy outputs arrive as ``baseline`` and ``reform`` dicts,
# whose microdata columns sit beside their ``<entity>_weight`` columns. In a
# module that imports microdf, a string-keyed read from either is a microdata
# column.
MICRODATA_DICT_NAMES = frozenset({"baseline", "reform"})
# Modules allowed to read raw values from weighted microdata. The Public API has
# none yet; a module that has to strip weights becomes the one designated here.
WEIGHT_STRIPPING_MODULES: frozenset[str] = frozenset()

AGGREGATION = "weight aggregated as a value"
STRIPPING = "weights stripped"
LABEL_REDUCTION = "unweighted series reduced"


class Weighting(enum.Enum):
    """What an expression holds, as far as weights go."""

    WEIGHTED = "weighted"
    LABEL = "label"


@dataclass(frozen=True)
class Finding:
    """One place a check flags, with a line-independent baseline entry."""

    check: str
    path: str
    line: int
    function: str
    source: str

    @property
    def entry(self) -> str:
        """Return the baseline entry: path, enclosing function and expression."""
        return f"{self.path}::{self.function}::{self.source}"

    def __str__(self) -> str:
        """Describe the finding with its line, for assertion messages."""
        return f"{self.path}:{self.line} ({self.function}): {self.source}"


@dataclass
class Scope:
    """The names a module or function assigns, sorted by what they hold."""

    reads_microdata_dicts: bool
    weight_keys: set[str] = field(default_factory=set)
    weight_columns: set[str] = field(default_factory=set)
    weight_arrays: set[str] = field(default_factory=set)
    weighting: dict[str, Weighting] = field(default_factory=dict)

    def child(self) -> Scope:
        """Return a nested function's scope, which starts with these names."""
        return Scope(
            reads_microdata_dicts=self.reads_microdata_dicts,
            weight_keys=set(self.weight_keys),
            weight_columns=set(self.weight_columns),
            weight_arrays=set(self.weight_arrays),
            weighting=dict(self.weighting),
        )


def _dotted_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted_name(node.value)}.{node.attr}"
    return ""


def _called_name(call: ast.Call) -> str:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return ""


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _argument(call: ast.Call, position: int | None, name: str) -> ast.expr | None:
    if position is not None and len(call.args) > position:
        return call.args[position]
    return _keyword(call, name)


def _names_a_weight(node: ast.expr) -> bool:
    """Whether a string or f-string literal ends in ``_weight`` or ``_weights``."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.endswith(WEIGHT_SUFFIXES)
    if isinstance(node, ast.JoinedStr) and node.values:
        tail = node.values[-1]
        return (
            isinstance(tail, ast.Constant)
            and isinstance(tail.value, str)
            and tail.value.endswith(WEIGHT_SUFFIXES)
        )
    return False


def _is_weight_key(node: ast.expr, scope: Scope) -> bool:
    if isinstance(node, ast.Name):
        return node.id in scope.weight_keys
    return _names_a_weight(node)


def _is_weight_column(node: ast.expr, scope: Scope) -> bool:
    """Whether the expression is ``<frame>[<weight>]``, or a name assigned one."""
    if isinstance(node, ast.Name):
        return node.id in scope.weight_columns
    return isinstance(node, ast.Subscript) and _is_weight_key(node.slice, scope)


def _is_weight_array(node: ast.expr, scope: Scope) -> bool:
    if isinstance(node, ast.Name):
        return node.id in scope.weight_arrays
    return isinstance(node, ast.Attribute) and node.attr == "weights"


def _is_weight(node: ast.expr, scope: Scope) -> bool:
    return (
        _is_weight_key(node, scope)
        or _is_weight_column(node, scope)
        or _is_weight_array(node, scope)
    )


def _combined(weightings: list[Weighting | None]) -> Weighting | None:
    if Weighting.WEIGHTED in weightings:
        return Weighting.WEIGHTED
    if Weighting.LABEL in weightings:
        return Weighting.LABEL
    return None


def _constructed_weighting(call: ast.Call) -> Weighting | None:
    weights = _keyword(call, "weights")
    has_weights = weights is not None and not (
        isinstance(weights, ast.Constant) and weights.value is None
    )
    name = _called_name(call)
    if name == "MicroSeries":
        return Weighting.WEIGHTED if has_weights else Weighting.LABEL
    if name == "MicroDataFrame" and has_weights:
        return Weighting.WEIGHTED
    return None


def _call_weighting(call: ast.Call, scope: Scope) -> Weighting | None:
    if _called_name(call) in {"MicroSeries", "MicroDataFrame"}:
        return _constructed_weighting(call)
    if (
        isinstance(call.func, ast.Attribute)
        and call.func.attr in WEIGHTING_PRESERVING_METHODS
    ):
        return _weighting(call.func.value, scope)
    return None


def _subscript_weighting(subscript: ast.Subscript, scope: Scope) -> Weighting | None:
    if (
        scope.reads_microdata_dicts
        and isinstance(subscript.value, ast.Name)
        and subscript.value.id in MICRODATA_DICT_NAMES
        and isinstance(subscript.slice, ast.Constant)
        and isinstance(subscript.slice.value, str)
    ):
        return Weighting.WEIGHTED
    receiver = subscript.value
    if isinstance(receiver, ast.Attribute) and receiver.attr in {"loc", "iloc"}:
        receiver = receiver.value
    return _weighting(receiver, scope)


def _operands(node: ast.expr) -> list[ast.expr]:
    """Return the operands whose weighting an operator's result keeps."""
    if isinstance(node, ast.BinOp):
        return [node.left, node.right]
    if isinstance(node, ast.UnaryOp):
        return [node.operand]
    if isinstance(node, ast.Compare):
        return [node.left, *node.comparators]
    if isinstance(node, ast.BoolOp):
        return list(node.values)
    if isinstance(node, ast.IfExp):
        return [node.body, node.orelse]
    return []


def _weighting(node: ast.expr, scope: Scope) -> Weighting | None:
    """Return whether the expression holds weighted microdata or a label series."""
    if isinstance(node, ast.Name):
        return scope.weighting.get(node.id)
    if isinstance(node, ast.Call):
        return _call_weighting(node, scope)
    if isinstance(node, ast.Subscript):
        return _subscript_weighting(node, scope)
    return _combined([_weighting(operand, scope) for operand in _operands(node)])


def _assignments(body: list[ast.stmt]) -> list[tuple[str, ast.expr]]:
    """Return each ``name = value`` in a body, outside nested functions and classes."""
    assignments: list[tuple[str, ast.expr]] = []
    pending: list[ast.AST] = list(body)
    while pending:
        node = pending.pop()
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            continue
        if isinstance(node, ast.Assign):
            assignments.extend(
                (target.id, node.value)
                for target in node.targets
                if isinstance(target, ast.Name)
            )
        elif (
            isinstance(node, (ast.AnnAssign, ast.NamedExpr))
            and isinstance(node.target, ast.Name)
            and node.value is not None
        ):
            assignments.append((node.target.id, node.value))
        pending.extend(ast.iter_child_nodes(node))
    return assignments


def _with_assignments(scope: Scope, body: list[ast.stmt]) -> Scope:
    """Sort the body's assigned names into the scope, until nothing changes."""
    assignments = _assignments(body)
    changed = True
    while changed:
        changed = False
        for name, value in assignments:
            groups = (
                (scope.weight_keys, _is_weight_key(value, scope)),
                (scope.weight_columns, _is_weight_column(value, scope)),
                (scope.weight_arrays, _is_weight_array(value, scope)),
            )
            for names, matches in groups:
                if matches and name not in names:
                    names.add(name)
                    changed = True
            weighting = _combined([scope.weighting.get(name), _weighting(value, scope)])
            if weighting is not None and scope.weighting.get(name) is not weighting:
                scope.weighting[name] = weighting
                changed = True
    return scope


class _MicrodataWalker:
    """Walk a module with each function's scope and collect every finding."""

    def __init__(self, relative_path: str) -> None:
        self.relative_path = relative_path
        self.findings: list[Finding] = []
        self._called_functions: set[int] = set()

    def walk(self, tree: ast.Module, *, reads_microdata_dicts: bool) -> None:
        scope = _with_assignments(
            Scope(reads_microdata_dicts=reads_microdata_dicts), tree.body
        )
        self._walk(tree, scope, "<module>")

    def _walk(self, node: ast.AST, scope: Scope, function: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = (
                    child.name if function == "<module>" else f"{function}.{child.name}"
                )
                if isinstance(child, ast.ClassDef):
                    self._walk(child, scope, name)
                else:
                    self._walk(
                        child, _with_assignments(scope.child(), child.body), name
                    )
                continue
            self._check(child, scope, function)
            self._walk(child, scope, function)

    def _report(self, check: str, node: ast.expr, function: str) -> None:
        self.findings.append(
            Finding(
                check=check,
                path=self.relative_path,
                line=node.lineno,
                function=function,
                source=ast.unparse(node),
            )
        )

    def _check(self, node: ast.AST, scope: Scope, function: str) -> None:
        if isinstance(node, ast.Call):
            self._called_functions.add(id(node.func))
            self._check_aggregation(node, scope, function)
            self._check_stripping_call(node, scope, function)
            self._check_label_reduction(node, scope, function)
        elif (
            isinstance(node, ast.Attribute)
            and node.attr in STRIPPING_ATTRIBUTES
            and id(node) not in self._called_functions
            and _weighting(node.value, scope) is Weighting.WEIGHTED
        ):
            self._report(STRIPPING, node, function)

    def _check_aggregation(self, call: ast.Call, scope: Scope, function: str) -> None:
        name = _called_name(call)
        aggregated: ast.expr | None = None
        if name in WEIGHTED_AGGREGATORS:
            aggregated = _argument(call, *WEIGHTED_AGGREGATORS[name])
        elif name == "MicroSeries" and _keyword(call, "weights") is not None:
            aggregated = _argument(call, 0, "data")
        if aggregated is not None and _is_weight(aggregated, scope):
            self._report(AGGREGATION, call, function)
            return
        if (
            isinstance(call.func, ast.Attribute)
            and call.func.attr in WEIGHTED_REDUCTIONS
            and _is_weight_column(call.func.value, scope)
        ):
            self._report(AGGREGATION, call, function)

    def _check_stripping_call(
        self, call: ast.Call, scope: Scope, function: str
    ) -> None:
        if _dotted_name(call.func) in STRIPPING_FUNCTIONS:
            stripped = _argument(call, 0, "data")
        elif (
            isinstance(call.func, ast.Attribute) and call.func.attr in STRIPPING_METHODS
        ):
            stripped = call.func.value
        else:
            return
        if stripped is not None and _weighting(stripped, scope) is Weighting.WEIGHTED:
            self._report(STRIPPING, call, function)

    def _check_label_reduction(
        self, call: ast.Call, scope: Scope, function: str
    ) -> None:
        if (
            isinstance(call.func, ast.Attribute)
            and call.func.attr in WEIGHTED_REDUCTIONS
            and _weighting(call.func.value, scope) is Weighting.LABEL
        ):
            self._report(LABEL_REDUCTION, call, function)


def _imports_microdf(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "microdf"
        ):
            return True
        if isinstance(node, ast.Import) and any(
            alias.name.startswith("microdf") for alias in node.names
        ):
            return True
    return False


@cache
def _module_findings(path: Path) -> tuple[Finding, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    walker = _MicrodataWalker(path.relative_to(PROJECT_ROOT).as_posix())
    walker.walk(tree, reads_microdata_dicts=_imports_microdf(tree))
    return tuple(walker.findings)


def _package_findings(check: str) -> list[Finding]:
    modules = sorted(PACKAGE_ROOT.rglob("*.py"))
    assert modules, f"no modules under {PACKAGE_ROOT}"
    return [
        finding
        for module in modules
        for finding in _module_findings(module)
        if finding.check == check
    ]


def _fixture_sources(rule_id: str, fixture: str, check: str) -> list[str]:
    path = FIXTURES_ROOT / rule_id / fixture
    return [
        finding.source for finding in _module_findings(path) if finding.check == check
    ]


def _described(findings: list[Finding]) -> str:
    return "\n".join(str(finding) for finding in findings)


def test_weights_are_never_aggregated_as_values() -> None:
    findings = _package_findings(AGGREGATION)
    assert findings == [], (
        "a weight is aggregated as a value, which weights it by itself (the sum "
        "of squared weights, as in #767); count entities with a plain sum of the "
        "weights instead:\n" + _described(findings)
    )


def test_weight_stripping_stays_in_the_designated_module() -> None:
    findings = [
        finding
        for finding in _package_findings(STRIPPING)
        if finding.path not in WEIGHT_STRIPPING_MODULES
    ]
    assert findings == [], (
        "raw values read from weighted microdata, outside the designated module; "
        "an unweighted total of them is a sample total, the mirror image of #767. "
        "Keep the weights, or decide with a reviewer to move the read into a "
        "designated module:\n" + _described(findings)
    )


def test_unweighted_series_are_only_labels() -> None:
    findings = _package_findings(LABEL_REDUCTION)
    assert findings == [], (
        "a MicroSeries built without weights= is reduced; such a series is a "
        "label, only for grouping or filtering, so reduce the weighted series "
        "grouped or filtered by it:\n" + _described(findings)
    )


def test_rule_proof_weights_not_aggregated_as_values() -> None:
    """Proof for rule api.microdata.weights-not-aggregated-as-values."""
    rule_id = "api.microdata.weights-not-aggregated-as-values"
    assert _fixture_sources(rule_id, "bad_budget.py", AGGREGATION) == [
        "_sum_output_variable(baseline, 'household_weight', entity='household')",
        "MicroSeries(baseline['household_weight'], "
        "weights=baseline['household_weight'])",
    ]
    assert _fixture_sources(rule_id, "good_budget.py", AGGREGATION) == []


def test_rule_proof_weight_stripping_confined() -> None:
    """Proof for rule api.microdata.weight-stripping-confined."""
    rule_id = "api.microdata.weight-stripping-confined"
    assert _fixture_sources(rule_id, "bad_net_income.py", STRIPPING) == [
        "np.array(baseline['household_net_income'])",
        "income.values",
    ]
    assert _fixture_sources(rule_id, "good_net_income.py", STRIPPING) == []


def test_rule_proof_unweighted_series_are_labels() -> None:
    """Proof for rule api.microdata.unweighted-series-are-labels."""
    rule_id = "api.microdata.unweighted-series-are-labels"
    assert _fixture_sources(rule_id, "bad_decile.py", LABEL_REDUCTION) == [
        "decile.mean()",
        "is_child.sum()",
    ]
    assert _fixture_sources(rule_id, "good_decile.py", LABEL_REDUCTION) == []
