from pathlib import Path


PACKAGE_ROOT = Path(__file__).parents[3] / "policyengine_api"


def test_runtime_sql_is_confined_to_the_data_access_layer():
    offenders = []
    for path in PACKAGE_ROOT.rglob("*.py"):
        if "data" in path.relative_to(PACKAGE_ROOT).parts:
            continue
        source = path.read_text(encoding="utf-8")
        if any(
            token in source
            for token in (
                "database.query(",
                "local_database.query(",
                "database.transaction(",
                "local_database.transaction(",
            )
        ):
            offenders.append(str(path.relative_to(PACKAGE_ROOT)))
    assert offenders == []
