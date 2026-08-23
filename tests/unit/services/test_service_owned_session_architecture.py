"""Architecture guards for service-owned SQLAlchemy sessions."""

import inspect
from pathlib import Path

import pytest

from policyengine_api.services.household_calculation_service import (
    HouseholdCalculationService,
)
from policyengine_api.services.household_service import HouseholdService
from policyengine_api.services.policy_service import PolicyService
from policyengine_api.services.reform_impacts_service import ReformImpactsService
from policyengine_api.services.report_output_service import ReportOutputService
from policyengine_api.services.simulation_service import SimulationService
from policyengine_api.services.user_policy_service import UserPolicyService
from policyengine_api.services.user_service import UserService


PROJECT_ROOT = Path(__file__).parents[3]
PACKAGE_ROOT = PROJECT_ROOT / "policyengine_api"


@pytest.mark.parametrize(
    ("service_type", "method_names"),
    [
        (
            HouseholdService,
            ("get_household", "create_household", "update_household"),
        ),
        (
            HouseholdCalculationService,
            ("calculate_stored_household", "calculate_household"),
        ),
        (
            PolicyService,
            ("get_policy", "get_policy_json", "search_policies", "set_policy"),
        ),
        (
            UserPolicyService,
            (
                "create_or_get_user_policy",
                "list_user_policies",
                "update_user_policy",
            ),
        ),
        (UserService, ("get_profile", "create_profile", "update_profile")),
        (
            SimulationService,
            (
                "get_or_create_simulation",
                "get_simulation",
                "update_simulation",
            ),
        ),
        (
            ReportOutputService,
            (
                "create_or_reuse_report_output",
                "resolve_report_output",
                "update_report_output",
            ),
        ),
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
def test_route_facing_service_methods_hide_persistence_dependencies(
    service_type,
    method_names,
):
    for method_name in method_names:
        parameters = inspect.signature(getattr(service_type, method_name)).parameters
        assert "session" not in parameters
        assert "session_factory" not in parameters


def test_presentation_layer_does_not_import_or_create_sqlalchemy_sessions():
    offenders = []
    presentation_paths = [
        *sorted((PACKAGE_ROOT / "routes").glob("*.py")),
        PACKAGE_ROOT / "country.py",
    ]
    banned_tokens = (
        "get_v1_session_factory",
        "from sqlalchemy",
        "import sqlalchemy",
        "sessionmaker",
    )
    for path in presentation_paths:
        source = path.read_text(encoding="utf-8")
        if any(token in source for token in banned_tokens):
            offenders.append(str(path.relative_to(PACKAGE_ROOT)))

    assert offenders == []


def test_removed_persistence_abstractions_stay_removed():
    removed_files = (
        "data/v1_daos.py",
        "data/data.py",
    )
    assert [path for path in removed_files if (PACKAGE_ROOT / path).exists()] == []
    assert not any((PACKAGE_ROOT / "endpoints").rglob("*.py"))
