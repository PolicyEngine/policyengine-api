from contextlib import ExitStack
import importlib
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from flask import Flask, Response

from policyengine_api.constants import get_report_output_cache_version
from policyengine_api.data.v1_models import (
    Household,
    Policy,
    ReportOutput,
    ReportOutputRun,
    Simulation,
)
from policyengine_api.extensions import cache
from policyengine_api.routes.household_routes import household_bp
from policyengine_api.routes.policy_routes import policy_bp
from policyengine_api.routes.report_output_routes import report_output_bp
from policyengine_api.routes.simulation_routes import simulation_bp
from policyengine_api.services.report_output_service import (
    ReportCreateResult,
    ReportOutputView,
)
from policyengine_api.services.household_calculation_service import (
    HouseholdCalculationResult,
)
from policyengine_api.services.simulation_service import SimulationCreateResult
from tests.contract.clients import (
    ASGIContractClient,
    ContractClient,
    FlaskContractClient,
)
from tests.contract.helpers import (
    assert_field_path_exists,
    assert_subset,
    response_json,
)
from tests.contract.registry import APP_V1_COMPATIBLE_ROUTE_CONTRACTS, ContractRequest


class _BudgetWindowEconomicImpactResult:
    def __init__(
        self,
        *,
        data: dict | None,
        progress: int | None = None,
        completed_years: list[str] | None = None,
        computing_years: list[str] | None = None,
        queued_years: list[str] | None = None,
        message: str | None = None,
        error: str | None = None,
        cache_status: str | None = None,
    ):
        self.data = data
        self.progress = progress
        self.completed_years = completed_years or []
        self.computing_years = computing_years or []
        self.queued_years = queued_years or []
        self.message = message
        self.error = error
        self.cache_status = cache_status

    @classmethod
    def completed(cls, data: dict):
        return cls(data=data, progress=100)

    def to_dict(self):
        return {
            "status": "ok",
            "data": self.data,
            "progress": self.progress,
            "completed_years": self.completed_years,
            "computing_years": self.computing_years,
            "queued_years": self.queued_years,
            "message": self.message,
            "error": self.error,
        }


class _EconomyService:
    def get_budget_window_economic_impact(self, **kwargs):
        return _BudgetWindowEconomicImpactResult.completed(
            {"kind": "budgetWindow", "windowSize": 1}
        )


class _MetadataService:
    def get_metadata(self, country_id: str):
        return {
            "current_law_id": 2 if country_id == "us" else 1,
            "economy_options": {
                "region": [{"name": country_id, "label": f"the {country_id}"}],
                "time_period": [{"name": 2026, "label": "2026"}],
            },
        }


def _load_blueprint_with_fake_service(
    *,
    service_module_name: str,
    route_module_name: str,
    fake_service_module,
    blueprint_name: str,
):
    sentinel = object()
    original_route_module = sys.modules.get(route_module_name, sentinel)
    original_service_module = sys.modules.get(service_module_name, sentinel)
    sys.modules.pop(route_module_name, None)
    sys.modules[service_module_name] = fake_service_module
    try:
        return getattr(importlib.import_module(route_module_name), blueprint_name)
    finally:
        if original_route_module is sentinel:
            sys.modules.pop(route_module_name, None)
        else:
            sys.modules[route_module_name] = original_route_module
        if original_service_module is sentinel:
            sys.modules.pop(service_module_name, None)
        else:
            sys.modules[service_module_name] = original_service_module


def _load_contract_metadata_blueprint():
    return _load_blueprint_with_fake_service(
        service_module_name="policyengine_api.services.metadata_service",
        route_module_name="policyengine_api.routes.metadata_routes",
        fake_service_module=SimpleNamespace(MetadataService=_MetadataService),
        blueprint_name="metadata_bp",
    )


def _load_contract_economy_blueprint():
    return _load_blueprint_with_fake_service(
        service_module_name="policyengine_api.services.economy_service",
        route_module_name="policyengine_api.routes.economy_routes",
        fake_service_module=SimpleNamespace(
            EconomyService=_EconomyService,
            EconomicImpactResult=object,
            BudgetWindowEconomicImpactResult=_BudgetWindowEconomicImpactResult,
        ),
        blueprint_name="economy_bp",
    )


def create_contract_flask_app() -> Flask:
    app = Flask(__name__)
    app.config.update(TESTING=True, CACHE_TYPE="NullCache")
    cache.init_app(app)
    app.register_blueprint(_load_contract_metadata_blueprint())
    app.register_blueprint(policy_bp)
    app.register_blueprint(household_bp)
    app.register_blueprint(_load_contract_economy_blueprint())
    app.register_blueprint(simulation_bp)
    app.register_blueprint(report_output_bp)

    @app.route("/liveness-check")
    def liveness_check():
        return Response("OK", status=200, mimetype="text/plain")

    @app.route("/readiness-check")
    def readiness_check():
        return Response("OK", status=200, mimetype="text/plain")

    return app


@pytest.fixture(params=("flask_direct", "fastapi_fallback"))
def contract_client(request) -> ContractClient:
    app = create_contract_flask_app()
    if request.param == "flask_direct":
        return FlaskContractClient(app)
    if request.param == "fastapi_fallback":
        return ASGIContractClient(app)
    raise AssertionError(f"Unknown contract client: {request.param}")


def _resolved_path(path: str) -> str:
    return (
        path.replace("{policy_id}", "22")
        .replace("{baseline_policy_id}", "2")
        .replace("{household_id}", "456")
        .replace("{simulation_id}", "11")
        .replace("{report_id}", "33")
    )


def _json_payload(contract: ContractRequest) -> dict | None:
    if contract.path == "/us/policy":
        return {"label": "Utah reform", "data": {"gov.example.parameter": 1}}
    if contract.path == "/us/household":
        return {"label": "Empty household", "data": {}}
    if contract.path == "/us/household/{household_id}":
        return {"label": "Updated household", "data": {"people": {"you": {}}}}
    if contract.path == "/us/calculate":
        return {"household": {"people": {"you": {}}}, "policy": {}}
    if contract.path == "/us/simulation":
        return {
            "population_id": "household-1",
            "population_type": "household",
            "policy_id": 22,
        }
    if contract.path == "/us/report":
        return {"simulation_1_id": 11, "simulation_2_id": None, "year": "2026"}
    return None


def _fake_country():
    return SimpleNamespace(
        metadata={},
        calculate=lambda household, policy: {
            "people": {"you": {"age": {"2026": 40}}},
            "policy": policy,
        },
    )


def _patched_route_dependencies():
    stack = ExitStack()
    stack.enter_context(
        patch(
            "policyengine_api.routes.policy_routes.policy_service.get_policy",
            return_value=Policy(
                id=22,
                country_id="us",
                label="Current law",
                api_version="1",
                policy_json={},
                policy_hash="hash-22",
            ),
        )
    )
    stack.enter_context(
        patch(
            "policyengine_api.routes.policy_routes.policy_service.set_policy",
            return_value=(123, "Policy created successfully", False),
        )
    )
    stack.enter_context(
        patch(
            "policyengine_api.routes.policy_routes.policy_service.search_policies",
            return_value=[
                Policy(
                    id=123,
                    country_id="us",
                    label="Tax reform",
                    api_version="1",
                    policy_json={},
                    policy_hash="hash-1",
                ),
                Policy(
                    id=124,
                    country_id="us",
                    label="Tax reform",
                    api_version="1",
                    policy_json={},
                    policy_hash="hash-1",
                ),
            ],
        )
    )
    stack.enter_context(
        patch(
            "policyengine_api.routes.household_routes.household_service.create_household",
            return_value=Household(
                id=456,
                country_id="us",
                label="Empty household",
                api_version="1",
                household_json={},
                household_hash="hash-456",
            ),
        )
    )
    stack.enter_context(
        patch(
            "policyengine_api.routes.household_routes.household_service.get_household",
            return_value=Household(
                id=456,
                country_id="us",
                label="Empty household",
                api_version="1",
                household_json={},
                household_hash="hash-456",
            ),
        )
    )
    stack.enter_context(
        patch(
            "policyengine_api.routes.household_routes.household_service.update_household",
            return_value=Household(
                id=456,
                country_id="us",
                label="Empty household",
                api_version="1",
                household_json={"people": {"you": {}}},
                household_hash="hash-456",
            ),
        )
    )
    stack.enter_context(
        patch(
            "policyengine_api.routes.household_routes.household_calculation_service.calculate_household",
            return_value=HouseholdCalculationResult(
                household={
                    "people": {"you": {"age": {"2026": 40}}},
                }
            ),
        )
    )
    stack.enter_context(
        patch(
            "policyengine_api.routes.simulation_routes.simulation_service.get_or_create_simulation",
            return_value=SimulationCreateResult(
                simulation=Simulation(
                    id=11,
                    country_id="us",
                    population_id="household-1",
                    population_type="household",
                    policy_id=22,
                    status="pending",
                ),
                created=True,
            ),
        )
    )
    stack.enter_context(
        patch(
            "policyengine_api.routes.simulation_routes.simulation_service.get_simulation",
            return_value=Simulation(id=11, status="pending", country_id="us"),
        )
    )
    stack.enter_context(
        patch(
            "policyengine_api.routes.report_output_routes.report_output_service.create_or_reuse_report_output",
            return_value=ReportCreateResult(
                view=ReportOutputView(
                    report_output=ReportOutput(
                        id=33,
                        country_id="us",
                        simulation_1_id=11,
                        simulation_2_id=None,
                        api_version=get_report_output_cache_version("us"),
                        status="pending",
                        year="2026",
                    ),
                    display_run=ReportOutputRun(
                        id="run-33",
                        report_output_id=33,
                        run_sequence=1,
                        status="pending",
                    ),
                ),
                created=True,
            ),
        )
    )
    stack.enter_context(
        patch(
            "policyengine_api.routes.report_output_routes.report_output_service.resolve_report_output",
            return_value=ReportOutputView(
                report_output=ReportOutput(
                    id=33,
                    country_id="us",
                    simulation_1_id=11,
                    simulation_2_id=None,
                    api_version=get_report_output_cache_version("us"),
                    status="pending",
                    year="2026",
                ),
                display_run=ReportOutputRun(
                    id="run-33",
                    report_output_id=33,
                    run_sequence=1,
                    status="pending",
                ),
            ),
        )
    )
    return stack


def _expected_subset(contract: ContractRequest) -> dict:
    if contract.path == "/us/policy":
        return {
            "status": "ok",
            "message": "Policy created successfully",
            "result": {"policy_id": 123},
        }
    if contract.path == "/us/policy/{policy_id}":
        return {"status": "ok", "message": None, "result": {"label": "Current law"}}
    if contract.path == "/us/policies":
        return {
            "status": "ok",
            "message": "Policies found",
            "result": [{"id": 123, "label": "Tax reform"}],
        }
    if contract.path == "/us/household":
        return {"status": "ok", "message": None, "result": {"household_id": 456}}
    if contract.path == "/us/household/{household_id}" and contract.method == "PUT":
        return {
            "status": "ok",
            "message": None,
            "result": {"household_id": 456, "household_json": {"people": {"you": {}}}},
        }
    if contract.path == "/us/household/{household_id}":
        return {"status": "ok", "result": {"id": 456, "label": "Empty household"}}
    if contract.path == "/us/calculate":
        return {
            "status": "ok",
            "message": None,
            "result": {"people": {"you": {"age": {"2026": 40}}}},
        }
    if contract.path in {"/us/metadata", "/uk/metadata"}:
        country_id = contract.path.strip("/").split("/")[0]
        return {
            "status": "ok",
            "message": None,
            "result": {
                "current_law_id": 2 if country_id == "us" else 1,
                "economy_options": {
                    "region": [{"name": country_id}],
                    "time_period": [{"name": 2026}],
                },
            },
        }
    if contract.path == "/us/simulation":
        return {
            "status": "ok",
            "message": "Simulation created successfully",
            "result": {"id": 11, "status": "pending"},
        }
    if contract.path == "/us/simulation/{simulation_id}":
        return {"status": "ok", "message": None, "result": {"id": 11}}
    if contract.path == "/us/report":
        return {
            "status": "ok",
            "message": "Report output created successfully",
            "result": {"id": 33, "status": "pending"},
        }
    if contract.path == "/us/report/{report_id}":
        return {"status": "ok", "message": None, "result": {"id": 33}}
    if "budget-window" in contract.path:
        return {
            "status": "ok",
            "message": None,
            "result": {"kind": "budgetWindow", "windowSize": 1},
            "progress": 100,
            "completed_years": [],
            "computing_years": [],
            "queued_years": [],
            "error": None,
        }
    raise AssertionError(f"Missing expected subset for {contract}")


@pytest.mark.parametrize(
    "contract",
    APP_V1_COMPATIBLE_ROUTE_CONTRACTS,
    ids=lambda contract: f"{contract.method} {contract.path}",
)
def test_app_v2_api_v1_route_contract(
    contract: ContractRequest,
    contract_client: ContractClient,
):
    with _patched_route_dependencies():
        response = contract_client.open(
            _resolved_path(contract.path),
            method=contract.method,
            json=_json_payload(contract),
        )

    assert response.status_code == contract.expected_status
    payload = response_json(response)
    assert_subset(payload, _expected_subset(contract))
    for field_path in contract.stable_response_fields:
        assert_field_path_exists(payload, field_path)


def test_health_routes_contract(contract_client: ContractClient):
    liveness = contract_client.open("/liveness-check", method="GET")
    readiness = contract_client.open("/readiness-check", method="GET")

    assert liveness.status_code == 200
    assert liveness.data == b"OK"
    assert "text/plain" in liveness.content_type
    assert readiness.status_code == 200
    assert readiness.data == b"OK"
    assert "text/plain" in readiness.content_type


def test_invalid_country_contract(contract_client: ContractClient):
    response = contract_client.open("/zz/metadata", method="GET")

    assert response.status_code == 400
    assert_subset(
        response_json(response),
        {
            "status": "error",
            "message": "Country zz not found. Available countries are: uk, us, ca, ng, il",
        },
    )
