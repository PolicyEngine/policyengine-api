"""Minimal reader for GitHub Actions workflow files.

The standard library has no YAML parser and the guard must run without
dependencies, so this reads only the subset these repositories use: block-style
``jobs:`` mappings, ``name:``/``uses:``/``run:`` keys (including ``|`` and ``>``
block scalars), and ``strategy.matrix`` lists. Anything outside that subset is
reported as unsupported rather than guessed at.

It answers three questions: does job X exist, does its run text (or reusable
workflow reference) contain a given invocation string, and how many lines of
code does each step's ``run:`` block hold?
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
    text: str


@dataclass(frozen=True)
class JobBlock:
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
        elif char == "#" and not in_single and not in_double:
            if index == 0 or line[index - 1].isspace():
                return line[:index].rstrip()
    return line.rstrip()


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def logical_lines(text: str, style: str) -> int:
    """Lines of code in a run: script, as the shell sees them.

    A folded (``>``) block is one command per paragraph, because YAML joins its
    lines with spaces. In a literal (``|``) block, a line ending in a backslash
    continues onto the next. Blank and comment-only lines don't count.
    """
    lines = [line for line in text.splitlines()]
    if style == ">":
        paragraphs, current = 0, False
        for line in lines:
            if line.strip():
                if not current:
                    paragraphs += 1
                current = True
            else:
                current = False
        return paragraphs
    count, continued = 0, False
    for line in lines:
        if not line.strip():
            continued = False
            continue
        if not continued:
            count += 1
        continued = line.rstrip().endswith("\\")
    return count


def _inline_list(value: str) -> tuple[str, ...]:
    inner = value.strip()[1:-1]
    return tuple(_unquote(item) for item in inner.split(",") if item.strip())


def _parse_job(job_id: str, lines: list[str], job_indent: int) -> JobBlock:
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
            if in_steps and item and item_indent is not None:
                if len(item.group(1)) == item_indent:
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
                code_lines=logical_lines(text, style),
                text=text,
            )
            for number, text, style in blocks
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
                jobs[current] = _parse_job(current, current_lines, job_indent)
            current, current_lines = match.group(1), []
        elif line.strip() and _indent(line) == job_indent:
            problems.append(f"unexpected line at job level: {line.strip()!r}")
        elif current:
            current_lines.append(line)
    if current:
        jobs[current] = _parse_job(current, current_lines, job_indent)
    return jobs, problems
