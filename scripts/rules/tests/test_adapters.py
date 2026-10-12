"""Tests for the agent-adapter check: CLAUDE.md and friends only point to AGENTS.md."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.rules.adapters import check_adapters
from scripts.rules.model import Agents
from scripts.rules.render import BEGIN

FIXTURES = Path(__file__).parent / "fixtures" / "adapters"
AGENTS = Agents(instructions="AGENTS.md", adapters=("CLAUDE.md",), max_adapter_lines=5)


def violations_for(adapter_text: str) -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "AGENTS.md").write_text("# Agent Instructions\n")
        (root / "CLAUDE.md").write_text(adapter_text)
        return [str(v) for v in check_adapters(AGENTS, root)]


class TestAdaptersProof(unittest.TestCase):
    def test_rule_proof_adapters(self) -> None:
        bad = (FIXTURES / "bad_CLAUDE.md").read_text()
        good = (FIXTURES / "good_CLAUDE.md").read_text()
        self.assertTrue(violations_for(bad))
        self.assertEqual(violations_for(good), [])


class AdapterTest(unittest.TestCase):
    def test_adapter_must_point_to_agents_md(self) -> None:
        self.assertIn("does not point to AGENTS.md", violations_for("# Claude\n")[0])

    def test_adapter_must_not_list_skills(self) -> None:
        text = "See `AGENTS.md`.\nRead `docs/engineering/skills/testing.md`.\n"
        self.assertIn("references other docs", violations_for(text)[0])

    def test_adapter_must_not_carry_the_rules_block(self) -> None:
        text = f"See `AGENTS.md`.\n{BEGIN}\n"
        self.assertIn("contains the generated rules block", violations_for(text)[0])

    def test_adapter_must_stay_short(self) -> None:
        text = "See `AGENTS.md`.\n" + "guidance\n" * 6
        self.assertIn("non-empty lines (limit 5)", violations_for(text)[0])

    def test_missing_adapter_is_left_to_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copy(FIXTURES / "good_CLAUDE.md", root / "OTHER.md")
            self.assertEqual(check_adapters(AGENTS, root), [])


if __name__ == "__main__":
    unittest.main()
