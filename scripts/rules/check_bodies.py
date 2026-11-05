"""What runs in a test's body, for the asserting-tests guard, scope by scope.

scripts/rules/check_index.py decides which tests check something from what
``BodyReader`` returns. Standard library only.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from scripts.rules.check_modules import Bindings, FunctionNode, parameters

if TYPE_CHECKING:
    from collections.abc import Iterable

COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
RECEIVER_NAMES = frozenset({"self", "cls"})


@dataclass
class Body:
    """What runs in a function's body, and the names each call can see.

    ``call_scopes`` holds, for each call, the names bound in the scopes around
    it (parameters, assignments, loop and comprehension variables), which hide
    a module-level helper of the same name. ``stand_in_calls`` holds the calls
    made with a ``self`` that isn't the test's: in a stand-in class's methods,
    or in a nested function with its own ``self`` parameter.
    """

    nodes: list[ast.AST]
    nested: frozenset[str]
    bindings: Bindings
    call_scopes: dict[int, frozenset[str]]
    stand_in_calls: frozenset[int]


def scope_names(statements: Iterable[ast.AST], bound: Iterable[str]) -> frozenset[str]:
    """Return the names a scope binds: ``bound`` plus its own assignments.

    Nested functions, classes, lambdas and comprehensions have scopes of their
    own, so the names bound inside them are left out.
    """
    names = set(bound)
    stack = list(statements)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(node, (ast.Lambda, *COMPREHENSIONS)):
            continue
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
            names.add(node.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        stack.extend(ast.iter_child_nodes(node))
    return frozenset(names)


@dataclass
class _Definition:
    """A function, class or lambda bound to a name inside a body."""

    node: ast.AST
    scope: frozenset[str]
    stand_in: bool


@dataclass
class BodyReader:
    """Collect the nodes of a function's body that run when the test does.

    Decorators and default arguments are left out. A function, class or
    lambda bound to a name inside the body counts only when the body refers to
    it by name, as a stand-in the code calls does; a used stand-in class
    counts with every method in it.
    """

    path: str
    nested: dict[str, list[_Definition]] = field(default_factory=dict)
    nodes: list[ast.AST] = field(default_factory=list)
    loaded: set[str] = field(default_factory=set)
    call_scopes: dict[int, frozenset[str]] = field(default_factory=dict)
    stand_in_calls: set[int] = field(default_factory=set)

    def read(self, function: FunctionNode) -> Body:
        """Read ``function``'s body and the stand-ins it uses."""
        scope = scope_names(function.body, parameters(function))
        self._visit(function.body, scope, stand_in=False)
        used: set[str] = set()
        while unused := (self.loaded & set(self.nested)) - used:
            for name in sorted(unused):
                used.add(name)
                for definition in self.nested[name]:
                    self._visit_definition(definition)
        bindings = Bindings()
        for node in self.nodes:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                bindings.add(self.path, node)
        return Body(
            self.nodes,
            frozenset(self.nested),
            bindings,
            self.call_scopes,
            frozenset(self.stand_in_calls),
        )

    def _defines(self, node: ast.AST) -> tuple[str, ast.AST] | None:
        """Return the name and definition a nested definition binds, if any."""
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return node.name, node
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Lambda)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            return node.targets[0].id, node.value
        return None

    def _visit(
        self, statements: Iterable[ast.AST], scope: frozenset[str], *, stand_in: bool
    ) -> None:
        stack = list(statements)
        while stack:
            current = stack.pop()
            defined = self._defines(current)
            if defined is not None:
                name, definition = defined
                self.nested.setdefault(name, []).append(
                    _Definition(definition, scope, stand_in)
                )
                continue
            if isinstance(current, ast.Lambda):
                self._visit_lambda(current, scope, stand_in=stand_in)
                continue
            if isinstance(current, COMPREHENSIONS):
                targets = scope_names(
                    [generator.target for generator in current.generators], ()
                )
                self._visit(
                    ast.iter_child_nodes(current), scope | targets, stand_in=stand_in
                )
                continue
            self.nodes.append(current)
            if isinstance(current, ast.Call):
                self.call_scopes[id(current)] = scope
                if stand_in:
                    self.stand_in_calls.add(id(current))
            if isinstance(current, ast.Name) and isinstance(current.ctx, ast.Load):
                self.loaded.add(current.id)
            stack.extend(ast.iter_child_nodes(current))

    def _visit_lambda(
        self, node: ast.Lambda, scope: frozenset[str], *, stand_in: bool
    ) -> None:
        own = parameters(node)
        self._visit(
            [node.body], scope | own, stand_in=stand_in or bool(own & RECEIVER_NAMES)
        )

    def _visit_function(
        self, node: FunctionNode, scope: frozenset[str], *, stand_in: bool
    ) -> None:
        own = parameters(node)
        inner = scope | scope_names(node.body, own)
        self._visit(node.body, inner, stand_in=stand_in or bool(own & RECEIVER_NAMES))

    def _visit_definition(self, definition: _Definition) -> None:
        node = definition.node
        if isinstance(node, ast.ClassDef):
            for statement in node.body:
                if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self._visit_function(statement, definition.scope, stand_in=True)
                else:
                    self._visit([statement], definition.scope, stand_in=True)
        elif isinstance(node, ast.Lambda):
            self._visit_lambda(node, definition.scope, stand_in=definition.stand_in)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self._visit_function(node, definition.scope, stand_in=definition.stand_in)
