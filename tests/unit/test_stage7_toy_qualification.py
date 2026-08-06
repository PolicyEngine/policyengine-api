from pathlib import Path

from policyengine_api.scripts.qualify_stage7_toy import (
    compare_stage7_schema,
    qualify_stage7_toy,
)


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


def test_schema_comparison_is_read_only_and_reports_no_fresh_database_drift(
    tmp_path: Path,
):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'comparison.db'}"
    qualify_stage7_toy(database_url)
    assert compare_stage7_schema(database_url) == []
