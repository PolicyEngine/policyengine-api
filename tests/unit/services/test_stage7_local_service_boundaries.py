import inspect
from pathlib import Path

import pytest

from policyengine_api.services.ai_analysis_service import AIAnalysisService
from policyengine_api.services.reform_impacts_service import ReformImpactsService
from policyengine_api.services.simulation_analysis_service import (
    SimulationAnalysisService,
)
from policyengine_api.services.tracer_analysis_service import TracerAnalysisService


SERVICE_ROOT = Path(__file__).parents[3] / "policyengine_api" / "services"


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


@pytest.mark.parametrize(
    ("service_type", "method_names"),
    [
        (AIAnalysisService, ("get_existing_analysis", "trigger_ai_analysis")),
        (SimulationAnalysisService, ("execute_analysis",)),
        (TracerAnalysisService, ("execute_analysis", "get_tracer")),
        (
            ReformImpactsService,
            (
                "get_recent_reform_impacts",
                "get_all_reform_impacts",
                "get_all_reform_impacts_by_options_hash_prefix",
                "set_reform_impact",
                "delete_reform_impact",
                "set_error_reform_impact",
                "set_complete_reform_impact",
            ),
        ),
    ],
)
def test_local_service_public_methods_do_not_accept_persistence(
    service_type,
    method_names,
):
    for method_name in method_names:
        parameters = inspect.signature(getattr(service_type, method_name)).parameters
        assert "session" not in parameters
        assert "session_factory" not in parameters


def test_analysis_routes_do_not_manage_sessions():
    route_root = SERVICE_ROOT.parent / "routes"
    for module_name in (
        "simulation_analysis_routes.py",
        "tracer_analysis_routes.py",
    ):
        source = (route_root / module_name).read_text(encoding="utf-8")
        assert "get_v1_session_factory" not in source
        assert "sqlalchemy" not in source


def test_reform_impact_route_does_not_manage_sessions():
    source = (SERVICE_ROOT.parent / "routes" / "reform_impact_routes.py").read_text(
        encoding="utf-8"
    )
    assert "get_v1_session_factory" not in source
    assert "sqlalchemy" not in source


def test_economy_service_delegates_persistence_without_opening_sessions():
    source = (SERVICE_ROOT / "economy_service.py").read_text(encoding="utf-8")
    assert "get_v1_session_factory" not in source
