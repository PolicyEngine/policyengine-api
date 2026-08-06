from pathlib import Path

from policyengine_api.scripts.stage7_database import assert_safe_toy_database_url
import pytest


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


@pytest.mark.parametrize(
    "database_url",
    [
        "mysql+pymysql://toy:toy@127.0.0.1:3307/policyengine_stage7_toy",
        "mysql+pymysql://toy:toy@localhost:3307/custom_toy",
    ],
)
def test_toy_database_safety_guard_accepts_only_local_mysql_toy_databases(
    database_url: str,
):
    assert_safe_toy_database_url(database_url)


@pytest.mark.parametrize(
    "database_url",
    [
        "mysql+pymysql://toy:toy@prod.example.com/policyengine_stage7_toy",
        "mysql+pymysql://toy:toy@127.0.0.1/policyengine",
        "postgresql://toy:toy@127.0.0.1/policyengine_stage7_toy",
        "sqlite+pysqlite:///policyengine_stage7_toy.db",
    ],
)
def test_toy_database_safety_guard_rejects_unsafe_targets(database_url: str):
    with pytest.raises(ValueError, match="local MySQL.*_toy"):
        assert_safe_toy_database_url(database_url)


def test_stage7_toy_database_has_local_scaffold_and_test_targets():
    repo = Path(__file__).parents[2]
    compose = (repo / "compose.stage7-toy.yml").read_text(encoding="utf-8")
    makefile = (repo / "Makefile").read_text(encoding="utf-8")

    assert "mysql:8.0" in compose
    assert "policyengine_stage7_toy" in compose
    assert "healthcheck:" in compose
    assert "stage7-toy-up:" in makefile
    assert "stage7-toy-test:" in makefile
    assert "stage7-toy-down:" in makefile
