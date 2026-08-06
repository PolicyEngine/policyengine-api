from pathlib import Path

from policyengine_api.scripts.qualify_stage7_toy import qualify_stage7_toy


def test_toy_qualification_exercises_migrated_data_paths(tmp_path: Path):
    result = qualify_stage7_toy(f"sqlite+pysqlite:///{tmp_path / 'stage7-toy.db'}")
    assert result == {
        "alembic_head": True,
        "policy": True,
        "household": True,
        "user": True,
        "simulation": True,
        "report": True,
        "analysis": True,
        "tracer": True,
        "reform_impact": True,
    }


def test_legacy_daos_have_been_removed():
    package = Path(__file__).parents[2] / "policyengine_api"
    sources = "\n".join(
        path.read_text(encoding="utf-8") for path in package.rglob("*.py")
    )
    assert "LegacyPolicyDAO" not in sources
    assert "LegacyHouseholdDAO" not in sources
    assert "LegacyUserDAO" not in sources
    assert "LegacySimulationDAO" not in sources
    assert "LegacyReportDAO" not in sources
