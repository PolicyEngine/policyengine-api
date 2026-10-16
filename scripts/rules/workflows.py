"""Minimal reader for GitHub Actions workflow files.

The standard library has no YAML parser and the guard must run without
dependencies, so this reads only the subset these repositories use: block-style
``jobs:`` mappings, ``name:``/``uses:``/``run:`` keys (including ``|`` and ``>``
block scalars), and ``strategy.matrix`` lists. Anything outside that subset is
reported as unsupported rather than guessed at.

It answers three questions: does job X exist, does its run text (or reusable
workflow reference) contain a given invocation string, and does each step's
``run:`` block hold more than one line of code (or chain several commands)?
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_KEY = re.compile(r"^(\s*)(-\s+)?([A-Za-z0-9_-]+):\s*(.*)$")
_LIST_ITEM = re.compile(r"^(\s*)-\s+(.*)$")
_UNSUPPORTED = re.compile(r"(<<:|:\s*[&*][A-Za-z0-9_-]+\s*$)")


@dataclass(frozen=True)
class RunBlock:
    """One step's ``run:`` script."""

    step: str
    code_lines: int
    chained: bool
    text: str

    @property
    def single_line(self) -> bool:
        """Whether the block is at most one line of code with no chained commands."""
        return self.code_lines <= 1 and not self.chained


@dataclass(frozen=True)
class JobBlock:
    """One workflow job: its run text, step names, ``uses:`` references and matrix."""

    id: str
    name: str
    run_text: str
    uses: str
    step_names: tuple[str, ...]
    step_uses: tuple[str, ...] = ()
    matrix: dict[str, tuple[str, ...]] = field(default_factory=dict)
    run_blocks: tuple[RunBlock, ...] = ()

    def invokes(self, invocation: str) -> bool:
        """Whether the job's commands or actions mention ``invocation``."""
        return (
            invocation in self.run_text
            or invocation in self.uses
            or any(invocation in action for action in self.step_uses)
        )


def _strip_comment(line: str) -> str:
    in_single = in_double = False
    for index, char in enumerate(line):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif (
            char == "#"
            and not in_single
            and not in_double
            and (index == 0 or line[index - 1].isspace())
        ):
            return line[:index].rstrip()
    return line.rstrip()


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def code_lines(text: str) -> int:
    """Lines of code in a run: script: every non-empty, non-comment line.

    The lines of a folded (``>``) block and backslash-continued lines each
    count, because each is a line written in the workflow.
    """
    return sum(1 for line in text.splitlines() if line.strip())


_CHAIN_OPERATORS = ("&&", "||", ";")


def chains_commands(text: str) -> bool:
    """Whether a line chains commands with ``&&``, ``||`` or ``;``.

    Operators inside quotes or GitHub ``${{ }}`` expressions don't count. A
    single pipeline (``a | b``) is one command and is allowed.
    """
    for line in text.splitlines():
        index, quote = 0, ""
        while index < len(line):
            char = line[index]
            if quote:
                if char == "\\" and quote == '"':
                    index += 2
                    continue
                if char == quote:
                    quote = ""
            elif line.startswith("${{", index):
                end = line.find("}}", index)
                index = len(line) if end == -1 else end + 2
                continue
            elif char == "\\":
                index += 2
                continue
            elif char in "'\"":
                quote = char
            elif any(line.startswith(op, index) for op in _CHAIN_OPERATORS):
                return True
            index += 1
    return False


def _inline_list(value: str) -> tuple[str, ...]:
    inner = value.strip()[1:-1]
    return tuple(_unquote(item) for item in inner.split(",") if item.strip())


def _parse_job(job_id: str, lines: list[str]) -> JobBlock:
    name = ""
    uses = ""
    step_uses: list[str] = []
    runs: list[str] = []
    steps: list[str] = []
    matrix: dict[str, tuple[str, ...]] = {}
    body_indent = None
    # Step tracking, so each run: block can be attributed to its step.
    item_indent: int | None = None
    in_steps = False
    step_index = 0
    step_key_column = -1
    step_labels: dict[int, str] = {}
    blocks: list[tuple[int, str, str]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        match = _KEY.match(line)
        if not match:
            item = _LIST_ITEM.match(line)
            if (
                in_steps
                and item
                and item_indent is not None
                and len(item.group(1)) == item_indent
            ):
                step_index += 1
            index += 1
            continue
        leading, dash, key, value = match.groups()
        key_column = len(leading) + (len(dash) if dash else 0)
        if body_indent is None and not dash:
            body_indent = key_column
        top_level = not dash and key_column == body_indent
        if top_level:
            in_steps = key == "steps" and not value
            item_indent = None
        elif in_steps and dash:
            if item_indent is None:
                item_indent = len(leading)
            if len(leading) == item_indent:
                step_index += 1
                step_key_column = key_column
        if in_steps and key == "name" and key_column == step_key_column:
            step_labels[step_index] = _unquote(value)

        if key == "name" and top_level:
            name = _unquote(value)
        elif key == "name":
            steps.append(_unquote(value))
        elif key == "uses" and top_level:
            uses = _unquote(value)
        elif key == "uses":
            step_uses.append(_unquote(value))
        elif key == "run":
            if value.strip()[:1] in ("|", ">"):
                block = []
                index += 1
                while index < len(lines) and (
                    not lines[index].strip() or _indent(lines[index]) > key_column
                ):
                    block.append(lines[index].strip())
                    index += 1
                runs.append("\n".join(block))
                blocks.append((step_index, "\n".join(block), value.strip()[:1]))
                continue
            runs.append(_unquote(value))
            blocks.append((step_index, _unquote(value), "|"))
        elif key == "matrix" and not value:
            index += 1
            while index < len(lines) and (
                not lines[index].strip() or _indent(lines[index]) > key_column
            ):
                entry = _KEY.match(lines[index])
                if entry and not entry.group(2):
                    entry_key, entry_value = entry.group(3), entry.group(4)
                    entry_column = len(entry.group(1))
                    if entry_value.startswith("["):
                        matrix[entry_key] = _inline_list(entry_value)
                        index += 1
                        continue
                    items = []
                    index += 1
                    while index < len(lines) and (
                        not lines[index].strip()
                        or _indent(lines[index]) >= entry_column
                    ):
                        item = _LIST_ITEM.match(lines[index])
                        if not item or _KEY.match(lines[index]):
                            break
                        items.append(_unquote(item.group(2)))
                        index += 1
                    matrix[entry_key] = tuple(items)
                    continue
                index += 1
            continue
        index += 1
    return JobBlock(
        id=job_id,
        name=name or job_id,
        run_text="\n".join(runs),
        uses=uses,
        step_uses=tuple(step_uses),
        step_names=tuple(steps),
        matrix=matrix,
        run_blocks=tuple(
            RunBlock(
                step=step_labels.get(number) or f"step {number}",
                code_lines=code_lines(text),
                chained=chains_commands(text),
                text=text,
            )
            for number, text, _style in blocks
        ),
    )


def parse_jobs(text: str) -> tuple[dict[str, JobBlock], list[str]]:
    """Return the jobs in a workflow, plus descriptions of unsupported constructs."""
    lines = [_strip_comment(line) for line in text.splitlines()]
    problems = [
        f"line {number}: YAML anchors/aliases/merge keys are not supported"
        for number, line in enumerate(lines, 1)
        if _UNSUPPORTED.search(line)
    ]

    start = next(
        (i for i, line in enumerate(lines) if re.match(r"^jobs:\s*$", line)), None
    )
    if start is None:
        if any(re.match(r"^jobs:\s*\S", line) for line in lines):
            problems.append("flow-style 'jobs:' mapping is not supported")
        return {}, problems

    body: list[str] = []
    for line in lines[start + 1 :]:
        if line.strip() and _indent(line) == 0:
            break
        body.append(line)

    job_indent = next((_indent(line) for line in body if line.strip()), 0)
    jobs: dict[str, JobBlock] = {}
    current: str | None = None
    current_lines: list[str] = []
    for line in body:
        match = re.match(rf"^ {{{job_indent}}}([A-Za-z0-9_-]+):\s*$", line)
        if match and _indent(line) == job_indent:
            if current:
                jobs[current] = _parse_job(current, current_lines)
            current, current_lines = match.group(1), []
        elif line.strip() and _indent(line) == job_indent:
            problems.append(f"unexpected line at job level: {line.strip()!r}")
        elif current:
            current_lines.append(line)
    if current:
        jobs[current] = _parse_job(current, current_lines)
    return jobs, problems
