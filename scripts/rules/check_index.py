"""Which test functions check something: the analysis behind asserting-tests.

``CheckIndex`` reads test modules (with scripts/rules/check_modules.py), finds
the tests pytest and unittest collect from them, and decides whether each one
checks something (reading its body with scripts/rules/check_bodies.py),
following the helpers it calls. scripts/rules/asserting_tests.py describes
what counts as a check and holds the rule. Standard library only.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from scripts.rules.check_bodies import Body, BodyReader
from scripts.rules.check_modules import (
    CLASS,
    FUNCTION,
    IMPORT,
    PYTEST,
    SEPARATOR,
    UNITTEST,
    Bindings,
    FunctionNode,
    ParsedClass,
    ParsedModule,
    UncheckedTest,
    assigned_names,
    decorator_names,
    defines_constructor,
    dunder_test,
    is_direct_check,
    is_test_code,
    module_path,
    module_statements,
    parse_module,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

MAX_REEXPORT_DEPTH = 5

Key = tuple[object, ...]
# A collected test: its name, the module and function that define it, the
# class it is collected from (for self), and the line to report in the file.
Collected = tuple[str, ParsedModule, FunctionNode, ParsedClass | None, int]


@dataclass
class _Search:
    """State of one depth-first search for checks through helpers.

    Each helper gets an index that only grows within the search. A helper
    reached again while it, or a helper whose result rests on it, is still
    unresolved counts as checking nothing for now; ``pending`` holds those
    results, in finishing order, until the helper that started their cycle is
    done, as in Tarjan's strongly connected components algorithm.
    """

    next_index: int = 0
    open: dict[Key, int] = field(default_factory=dict)
    pending: list[tuple[Key, int]] = field(default_factory=list)
    pending_lowest: dict[Key, int] = field(default_factory=dict)
    lowest: int = 0

    def settle(
        self, index: int, results: dict[Key, bool], *, value: bool | None
    ) -> None:
        """Settle pending helpers after ``index``; store ``value`` unless None."""
        while self.pending and self.pending[-1][1] > index:
            key, _ = self.pending.pop()
            del self.pending_lowest[key]
            if value is not None:
                results[key] = value


def _nearest(values: Iterator[bool | None]) -> bool | None:
    return next((value for value in values if value is not None), None)


def _is_test_case_base(base: ast.expr) -> bool:
    name = (
        base.id
        if isinstance(base, ast.Name)
        else base.attr
        if isinstance(base, ast.Attribute)
        else ""
    )
    return name.endswith("TestCase")


class CheckIndex:
    """Which tests and helpers check something, across the repository's modules."""

    def __init__(self, root: Path) -> None:
        """Index modules under ``root``, reading each one only when needed."""
        self.root = root
        self._modules: dict[str, ParsedModule | None] = {}
        self._results: dict[Key, bool] = {}
        self._orders: dict[tuple[str, int, int], list[ParsedClass]] = {}
        self._search = _Search()

    # --- Modules and names ------------------------------------------------

    def _read(self, path: str) -> str:
        return (self.root / path).read_text(encoding="utf-8", errors="replace")

    def _test_module(self, path: str, text: str | None) -> ParsedModule:
        """Parse the test module itself; raise SyntaxError if it doesn't parse."""
        module = parse_module(path, self._read(path) if text is None else text)
        self._modules[path] = module
        return module

    def _test_code_module(self, stem: str) -> ParsedModule | None:
        """Return the test-code module at path stem ``stem``, if it parses."""
        for candidate in (f"{stem}.py", f"{stem}/__init__.py"):
            if not ((self.root / candidate).is_file() and is_test_code(candidate)):
                continue
            if candidate not in self._modules:
                try:
                    self._modules[candidate] = parse_module(
                        candidate, self._read(candidate)
                    )
                except (SyntaxError, ValueError):
                    self._modules[candidate] = None
            return self._modules[candidate]
        return None

    def _resolve(
        self, bindings: Bindings, name: str, depth: int = 0
    ) -> tuple[ParsedModule, str] | None:
        """Resolve an imported name to the test-code module that defines it.

        Re-exports and star imports are followed a few modules deep.
        """
        if depth > MAX_REEXPORT_DEPTH:
            return None
        sources = (
            [bindings.imports[name]]
            if name in bindings.imports
            else [(stem, name) for stem in bindings.star_sources]
        )
        for stem, original in sources:
            target = self._test_code_module(stem)
            if target is None:
                continue
            if original in target.functions or original in target.classes:
                return target, original
            found = self._resolve(target.bindings, original, depth + 1)
            if found is not None:
                return found
        return None

    def _function_from(
        self, bindings: Bindings, name: str
    ) -> tuple[ParsedModule, FunctionNode, None] | None:
        found = self._resolve(bindings, name)
        if found is None or found[1] not in found[0].functions:
            return None
        return found[0], found[0].functions[found[1]], None

    def _module_named(self, module: ParsedModule, name: str) -> ParsedModule | None:
        """Return the test-code module a name in ``module`` refers to, if any."""
        if name in module.bindings.modules:
            return self._test_code_module(module.bindings.modules[name])
        if name in module.bindings.imports:
            stem, original = module.bindings.imports[name]
            return self._test_code_module(f"{stem}/{original}")
        return None

    def _class_named(
        self, module: ParsedModule, expression: ast.expr
    ) -> ParsedClass | None:
        """Resolve a base-class expression to a class in test code, if it can."""
        if isinstance(expression, ast.Name):
            if module.last_kinds.get(expression.id) == CLASS:
                return ParsedClass(module, module.classes[expression.id])
            found = self._resolve(module.bindings, expression.id)
            if found is not None and found[1] in found[0].classes:
                return ParsedClass(found[0], found[0].classes[found[1]])
        elif isinstance(expression, ast.Attribute) and isinstance(
            expression.value, ast.Name
        ):
            target = self._module_named(module, expression.value.id)
            if target is not None and expression.attr in target.classes:
                return ParsedClass(target, target.classes[expression.attr])
        return None

    # --- Classes ----------------------------------------------------------

    def _order(
        self, cls: ParsedClass, active: frozenset[tuple[str, int, int]] = frozenset()
    ) -> list[ParsedClass]:
        """Return ``cls`` and its bases in Python's method resolution order.

        Only bases in test code resolve. An inconsistent hierarchy keeps the
        bases in the order they first appear.
        """
        if cls.key in self._orders:
            return self._orders[cls.key]
        if cls.key in active:
            return [cls]
        bases = [
            resolved
            for base in cls.node.bases
            if (resolved := self._class_named(cls.module, base)) is not None
        ]
        orders = [self._order(base, active | {cls.key}) for base in bases]
        merged = _merge([*(list(order) for order in orders), list(bases)])
        result = [cls, *merged]
        if not active:
            self._orders[cls.key] = result
        return result

    def _collection(self, cls: ParsedClass, runner: str, name: str) -> str | None:
        """Return how ``runner`` collects ``cls`` under ``name``, or None."""
        order = self._order(cls)
        is_test_case = any(
            _is_test_case_base(base) for member in order for base in member.node.bases
        )
        if runner == UNITTEST:
            # unittest discover collects TestCase subclasses and ignores __test__.
            return UNITTEST if is_test_case else None
        switch = _nearest(dunder_test(member.node.body) for member in order)
        if switch is False:
            return None
        if is_test_case:
            return UNITTEST
        if (name.startswith("Test") or switch is True) and not any(
            defines_constructor(member.node) for member in order
        ):
            return PYTEST
        return None

    def _attribute(
        self, cls: ParsedClass, name: str
    ) -> tuple[ParsedModule, FunctionNode] | None:
        """Look ``name`` up on ``cls`` as Python does: the nearest class wins.

        In each class's body the last binding wins. A name bound to anything
        but a function there shadows the methods further up.
        """
        for member in self._order(cls):
            binding: FunctionNode | bool | None = None
            for node in module_statements(member.node.body):
                if (
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == name
                ):
                    binding = node
                elif name in assigned_names(node) or (
                    isinstance(node, ast.ClassDef) and node.name == name
                ):
                    binding = False
            if binding is False:
                return None
            if binding is not None:
                return member.module, binding
        return None

    def _class_tests(
        self,
        cls: ParsedClass,
        context: _Collecting,
        prefix: str,
        name: str,
        collection: str,
    ) -> Iterator[Collected]:
        qualified = f"{prefix}{name}{SEPARATOR}"
        names: list[str] = []
        for member in self._order(cls):
            for node in module_statements(member.node.body):
                if (
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name.startswith("test")
                    and node.name not in names
                ):
                    names.append(node.name)
        for test_name in names:
            found = self._attribute(cls, test_name)
            if found is None or "fixture" in decorator_names(found[1]):
                continue
            module, function = found
            line = function.lineno if module is context.module else context.anchor
            yield f"{qualified}{test_name}", module, function, cls, line
        if collection == PYTEST:
            yield from self._nested_class_tests(cls, context, qualified)

    def _nested_class_tests(
        self, cls: ParsedClass, context: _Collecting, qualified: str
    ) -> Iterator[Collected]:
        seen: set[str] = set()
        for member in self._order(cls):
            for node in module_statements(member.node.body):
                if not isinstance(node, ast.ClassDef) or node.name in seen:
                    continue
                seen.add(node.name)
                nested = ParsedClass(member.module, node)
                if nested.key in context.active:
                    continue
                collection = self._collection(nested, context.module.runner, node.name)
                if collection is None:
                    continue
                inner = context.entering(
                    nested,
                    node.lineno if member.module is context.module else context.anchor,
                )
                yield from self._class_tests(
                    nested, inner, qualified, node.name, collection
                )

    # --- Collection -------------------------------------------------------

    def _collected_tests(self, module: ParsedModule) -> Iterator[Collected]:
        """Yield each test the module's runner would collect from ``module``."""
        runner = module.runner
        if runner == PYTEST and dunder_test(module.tree.body) is False:
            return
        for node in module_statements(module.tree.body):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if (
                    runner == PYTEST
                    and node.name.startswith("test")
                    and module.last_kinds.get(node.name) == FUNCTION
                    and module.functions[node.name] is node
                    and "fixture" not in decorator_names(node)
                ):
                    yield node.name, module, node, None, node.lineno
            elif (
                isinstance(node, ast.ClassDef)
                and module.last_kinds.get(node.name) == CLASS
                and module.classes[node.name] is node
            ):
                yield from self._tests_of_class(
                    ParsedClass(module, node), module, node.name, node.lineno
                )
            elif isinstance(node, ast.ImportFrom):
                yield from self._imported_tests(module, node)

    def _tests_of_class(
        self, cls: ParsedClass, module: ParsedModule, name: str, line: int
    ) -> Iterator[Collected]:
        collection = self._collection(cls, module.runner, name)
        if collection is not None:
            context = _Collecting(module, line, frozenset({cls.key}))
            yield from self._class_tests(cls, context, "", name, collection)

    def _imported_tests(
        self, module: ParsedModule, node: ast.ImportFrom
    ) -> Iterator[Collected]:
        """Yield the tests a test module imports, which pytest also runs there."""
        for alias in node.names:
            if alias.name == "*":
                yield from self._star_imported_tests(module, node)
                continue
            bound = alias.asname or alias.name
            if module.last_kinds.get(bound) != IMPORT:
                continue
            yield from self._bound_tests(module, bound, node.lineno)

    def _star_imported_tests(
        self, module: ParsedModule, node: ast.ImportFrom
    ) -> Iterator[Collected]:
        stem = module_path(module.path, node.module, node.level)
        target = self._test_code_module(stem) if stem else None
        if target is None:
            return
        for name in sorted({*target.functions, *target.classes}):
            if not name.startswith("_") and name not in module.last_kinds:
                yield from self._defined_tests(module, target, name, name, node.lineno)

    def _bound_tests(
        self, module: ParsedModule, bound: str, line: int
    ) -> Iterator[Collected]:
        found = self._resolve(module.bindings, bound)
        if found is not None:
            yield from self._defined_tests(module, found[0], found[1], bound, line)

    def _defined_tests(
        self,
        module: ParsedModule,
        target: ParsedModule,
        original: str,
        bound: str,
        line: int,
    ) -> Iterator[Collected]:
        """Yield the tests ``target``'s ``original`` holds, imported as ``bound``."""
        if original in target.classes:
            yield from self._tests_of_class(
                ParsedClass(target, target.classes[original]), module, bound, line
            )
        elif (
            module.runner == PYTEST
            and bound.startswith("test")
            and "fixture" not in decorator_names(target.functions[original])
        ):
            yield bound, target, target.functions[original], None, line

    # --- Helpers and checks -----------------------------------------------

    def _helper(
        self,
        module: ParsedModule,
        function: FunctionNode,
        owner: ParsedClass | None,
        body: Body,
        call: ast.Call,
    ) -> tuple[ParsedModule, FunctionNode, ParsedClass | None] | None:
        """Return the helper ``call`` calls, if the guard can tell which it is."""
        called = call.func
        if isinstance(called, ast.Name):
            return self._named_helper(module, body, called.id, call)
        if not isinstance(called, ast.Attribute) or owner is None:
            return None
        if id(call) in body.stand_in_calls:
            return None
        receiver = called.value
        if isinstance(receiver, ast.Name) and receiver.id in {"self", "cls"}:
            found = self._attribute(owner, called.attr)
        elif (
            isinstance(receiver, ast.Call)
            and isinstance(receiver.func, ast.Name)
            and receiver.func.id == "super"
        ):
            found = self._super_attribute(owner, function, called.attr)
        else:
            return None
        return None if found is None else (found[0], found[1], owner)

    def _super_attribute(
        self, owner: ParsedClass, function: FunctionNode, name: str
    ) -> tuple[ParsedModule, FunctionNode] | None:
        """Look ``name`` up after the class that defines ``function``."""
        order = self._order(owner)
        for position, member in enumerate(order):
            if function in member.node.body:
                for later in order[position + 1 :]:
                    found = self._attribute(later, name)
                    if found is not None:
                        return found
                return None
        return None

    def _named_helper(
        self, module: ParsedModule, body: Body, name: str, call: ast.Call
    ) -> tuple[ParsedModule, FunctionNode, None] | None:
        """Resolve ``name(...)`` as Python would, from the call's scope outward."""
        if name in body.nested:
            return None
        if name in body.bindings.bound_names():
            return self._function_from(body.bindings, name)
        if name in body.call_scopes.get(id(call), frozenset()):
            return None
        kind = module.last_kinds.get(name)
        if kind == FUNCTION:
            return module, module.functions[name], None
        if kind in {IMPORT, None}:
            return self._function_from(module.bindings, name)
        return None

    def _checks(
        self, module: ParsedModule, function: FunctionNode, owner: ParsedClass | None
    ) -> bool:
        """Whether ``function`` checks something, directly or through a helper."""
        key: Key = (
            module.path,
            function.lineno,
            function.col_offset,
            None if owner is None else owner.key,
        )
        if key in self._results:
            return self._results[key]
        search = self._search
        if key in search.open or key in search.pending_lowest:
            reached = search.open.get(key, search.pending_lowest.get(key, 0))
            search.lowest = min(search.lowest, reached)
            return False
        index = search.next_index
        search.next_index += 1
        search.open[key] = index
        outer_lowest, search.lowest = search.lowest, index
        try:
            body = BodyReader(module.path).read(function)
            scopes = (body.bindings, module.bindings)
            result = any(
                is_direct_check(node, scopes, body.stand_in_calls)
                for node in body.nodes
            ) or any(
                (helper := self._helper(module, function, owner, body, node))
                is not None
                and self._checks(*helper)
                for node in body.nodes
                if isinstance(node, ast.Call)
            )
        finally:
            del search.open[key]
        lowest = search.lowest
        if result:
            # Pending helpers after this one may reach it, so they are
            # evaluated again later, against the stored True.
            self._results[key] = True
            search.settle(index, self._results, value=None)
        elif lowest >= index:
            # This helper started every cycle after it, and nothing it reaches
            # checks anything.
            self._results[key] = False
            search.settle(index, self._results, value=False)
        else:
            search.pending.append((key, index))
            search.pending_lowest[key] = lowest
        search.lowest = min(outer_lowest, lowest)
        return result

    def unchecked_tests(
        self, path: str, text: str | None = None
    ) -> list[UncheckedTest]:
        """Return the tests in module ``path`` that check nothing.

        Read ``text`` as the module's source when given. Raise SyntaxError when
        the module doesn't parse.
        """
        module = self._test_module(path, text)
        unchecked = []
        for name, defining_module, function, owner, line in self._collected_tests(
            module
        ):
            self._search = _Search()
            if not self._checks(defining_module, function, owner):
                unchecked.append(UncheckedTest(path, line, name))
        return unchecked


@dataclass(frozen=True)
class _Collecting:
    """Where collected tests are reported: the test module and a fallback line.

    ``anchor`` is the line in the test module for tests defined elsewhere, and
    ``active`` holds the classes being collected, so a class nested in itself
    ends.
    """

    module: ParsedModule
    anchor: int
    active: frozenset[tuple[str, int, int]]

    def entering(self, cls: ParsedClass, anchor: int) -> _Collecting:
        """Return the context for collecting a nested class."""
        return _Collecting(self.module, anchor, self.active | {cls.key})


def _merge(sequences: list[list[ParsedClass]]) -> list[ParsedClass]:
    """Merge base orders as Python's C3 linearization does."""
    result: list[ParsedClass] = []
    sequences = [list(sequence) for sequence in sequences if sequence]
    while sequences:
        for sequence in sequences:
            head = sequence[0]
            if not any(
                head.key in {member.key for member in other[1:]} for other in sequences
            ):
                break
        else:
            # Python would refuse this hierarchy; keep first appearances.
            head = sequences[0][0]
        result.append(head)
        sequences = [
            [member for member in sequence if member.key != head.key]
            for sequence in sequences
        ]
        sequences = [sequence for sequence in sequences if sequence]
    return result
