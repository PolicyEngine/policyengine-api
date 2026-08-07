from pathlib import Path

import pytest


SERVICE_ROOT = Path(__file__).parents[3] / "policyengine_api" / "services"
DAO_MODULE = SERVICE_ROOT.parent / "data" / "v1_daos.py"


@pytest.mark.parametrize(
    "module_name",
    [
        "ai_analysis_service.py",
        "reform_impacts_service.py",
        "tracer_analysis_service.py",
        "report_output_alias_service.py",
    ],
)
def test_local_data_services_do_not_issue_queries_directly(module_name):
    source = (SERVICE_ROOT / module_name).read_text(encoding="utf-8")
    assert ".query(" not in source
    assert "local_database" not in source
    assert "from policyengine_api.data import database" not in source


def test_migrated_local_domains_have_no_temporary_daos():
    source = DAO_MODULE.read_text(encoding="utf-8")
    assert "class AnalysisDAO" not in source
    assert "class ReformImpactDAO" not in source
    assert "class TracerDAO" not in source
