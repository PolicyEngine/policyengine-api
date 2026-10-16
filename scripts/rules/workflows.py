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
from typing import NamedTuple

_KEY = re.compile(r"^(\s*)(-\s+)?([A-Za-z0-9_-]+):\s*(.*)$")
_LIST_ITEM = re.compile(r"^(\s*)-\s+(.*)$")
_UNSUPPORTED = re.compile(r"(<<:|:\s*[&*][A-Za-z0-9_-]+\s*$)")
# A quoted scalar is at least its opening and closing quote.
_QUOTE_PAIR_LENGTH = 2


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
    if len(value) >= _QUOTE_PAIR_LENGTH and value[0] == value[-1] and value[0] in "'\"":
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


class _KeyLine(NamedTuple):
    """One ``key: value`` line of a job, with the column its key starts at."""

    leading: str
    dash: str | None
    key: str
    value: str
    column: int
    top_level: bool


class _JobReader:
    """Reads one job's lines, attributing each ``run:`` block to its step."""

    def __init__(self, lines: list[str]) -> None:
        self.lines = lines
        self.index = 0
        self.name = ""
        self.uses = ""
        self.step_uses: list[str] = []
        self.runs: list[str] = []
        self.steps: list[str] = []
        self.matrix: dict[str, tuple[str, ...]] = {}
        self.body_indent: int | None = None
        # Step tracking, so each run: block can be attributed to its step.
        self.item_indent: int | None = None
        self.in_steps = False
        self.step_index = 0
        self.step_key_column = -1
        self.step_labels: dict[int, str] = {}
        self.blocks: list[tuple[int, str, str]] = []

    def read(self) -> None:
        """Read every line of the job."""
        while self.index < len(self.lines):
            match = _KEY.match(self.lines[self.index])
            if match:
                self._read_key(match)
            else:
                self._count_bare_step(self.lines[self.index])
                self.index += 1

    def job_block(self, job_id: str) -> JobBlock:
        """Return what was read as a job named ``job_id`` unless it has a name."""
        return JobBlock(
            id=job_id,
            name=self.name or job_id,
            run_text="\n".join(self.runs),
            uses=self.uses,
            step_uses=tuple(self.step_uses),
            step_names=tuple(self.steps),
            matrix=self.matrix,
            run_blocks=tuple(
                RunBlock(
                    step=self.step_labels.get(number) or f"step {number}",
                    code_lines=code_lines(text),
                    chained=chains_commands(text),
                    text=text,
                )
                for number, text, _style in self.blocks
            ),
        )

    def _still_inside(self, column: int) -> bool:
        """Whether the current line is blank or indented past ``column``."""
        return self.index < len(self.lines) and (
            not self.lines[self.index].strip()
            or _indent(self.lines[self.index]) > column
        )

    def _count_bare_step(self, line: str) -> None:
        """Count a list item that is not a key (such as a quoted string) as a step."""
        item = _LIST_ITEM.match(line)
        if (
            self.in_steps
            and item
            and self.item_indent is not None
            and len(item.group(1)) == self.item_indent
        ):
            self.step_index += 1

    def _read_key(self, match: re.Match[str]) -> None:
        leading, dash, key, value = match.groups()
        column = len(leading) + (len(dash) if dash else 0)
        if self.body_indent is None and not dash:
            self.body_indent = column
        entry = _KeyLine(
            leading=leading,
            dash=dash,
            key=key,
            value=value,
            column=column,
            top_level=not dash and column == self.body_indent,
        )
        self._track_step(entry)
        if entry.key == "run" and entry.value.strip()[:1] in ("|", ">"):
            self._read_block_scalar(entry)
        elif entry.key == "matrix" and not entry.value:
            self._read_matrix(entry.column)
        else:
            self._record_scalar(entry)
            self.index += 1

    def _track_step(self, entry: _KeyLine) -> None:
        """Note when a new step starts, and the name it gives itself."""
        if entry.top_level:
            self.in_steps = entry.key == "steps" and not entry.value
            self.item_indent = None
        elif self.in_steps and entry.dash:
            if self.item_indent is None:
                self.item_indent = len(entry.leading)
            if len(entry.leading) == self.item_indent:
                self.step_index += 1
                self.step_key_column = entry.column
        if (
            self.in_steps
            and entry.key == "name"
            and entry.column == self.step_key_column
        ):
            self.step_labels[self.step_index] = _unquote(entry.value)

    def _record_scalar(self, entry: _KeyLine) -> None:
        """Record a one-line ``name:``, ``uses:`` or ``run:`` value."""
        if entry.key == "name" and entry.top_level:
            self.name = _unquote(entry.value)
        elif entry.key == "name":
            self.steps.append(_unquote(entry.value))
        elif entry.key == "uses" and entry.top_level:
            self.uses = _unquote(entry.value)
        elif entry.key == "uses":
            self.step_uses.append(_unquote(entry.value))
        elif entry.key == "run":
            self.runs.append(_unquote(entry.value))
            self.blocks.append((self.step_index, _unquote(entry.value), "|"))

    def _read_block_scalar(self, entry: _KeyLine) -> None:
        """Read a ``|`` or ``>`` run: block, one stripped line per script line."""
        block = []
        self.index += 1
        while self._still_inside(entry.column):
            block.append(self.lines[self.index].strip())
            self.index += 1
        self.runs.append("\n".join(block))
        self.blocks.append((self.step_index, "\n".join(block), entry.value.strip()[:1]))

    def _read_matrix(self, column: int) -> None:
        """Read the ``strategy.matrix`` entries nested under the key at ``column``."""
        self.index += 1
        while self._still_inside(column):
            entry = _KEY.match(self.lines[self.index])
            if entry and not entry.group(2):
                self._read_matrix_entry(entry)
            else:
                self.index += 1

    def _read_matrix_entry(self, entry: re.Match[str]) -> None:
        """Read one matrix key's values, written inline or as a block list."""
        key, value = entry.group(3), entry.group(4)
        self.index += 1
        if value.startswith("["):
            self.matrix[key] = _inline_list(value)
            return
        # Block list items may sit at the key's own column.
        list_column = len(entry.group(1)) - 1
        items = []
        while self._still_inside(list_column):
            item = _LIST_ITEM.match(self.lines[self.index])
            if not item or _KEY.match(self.lines[self.index]):
                break
            items.append(_unquote(item.group(2)))
            self.index += 1
        self.matrix[key] = tuple(items)


def _parse_job(job_id: str, lines: list[str]) -> JobBlock:
    reader = _JobReader(lines)
    reader.read()
    return reader.job_block(job_id)


def _jobs_body(lines: list[str], start: int) -> list[str]:
    """Return the lines after ``jobs:`` up to the next top-level key."""
    body: list[str] = []
    for line in lines[start + 1 :]:
        if line.strip() and _indent(line) == 0:
            break
        body.append(line)
    return body


def _split_jobs(body: list[str]) -> tuple[dict[str, JobBlock], list[str]]:
    """Parse each job under ``jobs:``, and describe any stray job-level line."""
    job_indent = next((_indent(line) for line in body if line.strip()), 0)
    jobs: dict[str, JobBlock] = {}
    problems: list[str] = []
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

    jobs, job_problems = _split_jobs(_jobs_body(lines, start))
    return jobs, problems + job_problems
