from pathlib import Path

from policyengine_api.constants import REPO


SKILL = REPO / "docs" / "engineering" / "skills" / "alembic-migrations.md"


def test_model_agnostic_alembic_skill_is_discoverable():
    assert SKILL.exists()
    assert "alembic-migrations.md" in (
        REPO / "docs" / "engineering" / "skills" / "README.md"
    ).read_text()
    for adapter in ("AGENTS.md", "CLAUDE.md", ".github/copilot-instructions.md"):
        assert "docs/engineering/skills/alembic-migrations.md" in (
            REPO / adapter
        ).read_text()


def test_alembic_skill_forbids_handwritten_ai_revisions():
    guidance = SKILL.read_text()
    assert "MUST NOT manually author Alembic revision scripts" in guidance
    assert "alembic revision --autogenerate" in guidance
    assert "dialect compatibility" in guidance
    assert "reversibility" in guidance
    assert "request a human migration decision" in guidance
