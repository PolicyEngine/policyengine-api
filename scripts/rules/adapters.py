"""Check that per-tool agent instruction files stay thin pointers.

``AGENTS.md`` is the one source of agent instructions: it lists the skills and
carries the generated Rules block. Tool adapters such as ``CLAUDE.md`` and
``.github/copilot-instructions.md`` only point to it. When an adapter starts
listing skills or rules itself, the copies drift apart, so this rejects it.
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.rules.model import Agents, Violation
from scripts.rules.render import BEGIN

_DOC_REFERENCE = re.compile(r"[\w./-]+\.md\b")


def check_adapters(agents: Agents, root: Path) -> list[Violation]:
    """Return a violation for each way an adapter stops being a short pointer.

    Missing adapter files are skipped rather than reported.
    """
    violations = []
    instructions = Path(agents.instructions).name
    for adapter in agents.adapters:
        path = root / adapter
        if not path.is_file():
            continue
        text = path.read_text()

        def v(message: str, fix: str) -> None:
            violations.append(Violation(None, "adapters", f"{adapter} {message}", fix))

        if instructions not in text:
            v(
                f"does not point to {instructions}",
                f"say that the guidance lives in {instructions}",
            )
        others = sorted(
            {
                ref
                for ref in _DOC_REFERENCE.findall(text)
                if Path(ref).name != instructions
            }
        )
        if others:
            v(
                f"references other docs ({', '.join(others)})",
                f"list skills and rules in {instructions} only; keep {adapter} a pointer",
            )
        if BEGIN in text:
            v(
                "contains the generated rules block",
                f"the block belongs in {instructions} only",
            )
        lines = sum(1 for line in text.splitlines() if line.strip())
        if lines > agents.max_adapter_lines:
            v(
                f"has {lines} non-empty lines (limit {agents.max_adapter_lines})",
                f"move the guidance into {instructions} or a skill",
            )
    return violations
