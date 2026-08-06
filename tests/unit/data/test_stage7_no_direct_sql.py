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


def test_ordinary_runtime_modules_no_longer_use_raw_sql_facade():
    relative_paths = (
        "endpoints/household.py",
        "endpoints/policy.py",
        "endpoints/simulation.py",
        "endpoints/economy/reform_impact.py",
        "country.py",
        "services/ai_analysis_service.py",
        "services/reform_impacts_service.py",
        "services/tracer_analysis_service.py",
    )
    for relative_path in relative_paths:
        source = (PACKAGE_ROOT / relative_path).read_text(encoding="utf-8")
        assert "runtime_sqlalchemy_dao" not in source


def test_report_orchestration_uses_typed_repositories_not_raw_sql():
    source = (PACKAGE_ROOT / "services/report_output_service.py").read_text(
        encoding="utf-8"
    )
    assert "SQLAlchemyDAO" not in source
    assert ".query(" not in source
    assert "exec_driver_sql" not in source


def test_typed_repository_module_has_no_raw_sql_compatibility_dao():
    source = (PACKAGE_ROOT / "data/v1_daos.py").read_text(encoding="utf-8")
    assert "SQLAlchemyDAO" not in source
    assert "runtime_sqlalchemy_dao" not in source
    assert "exec_driver_sql" not in source
