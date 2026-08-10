import inspect
from pathlib import Path

import pytest
from sqlalchemy import func, select

from policyengine_api.data.v1_models import Household
from policyengine_api.services.household_service import HouseholdService
from policyengine_api.services.policy_service import PolicyService
from policyengine_api.services.simulation_service import SimulationService
from policyengine_api.services.user_service import UserService


ROUTE_ROOT = Path(__file__).parents[3] / "policyengine_api" / "routes"


@pytest.mark.parametrize(
    ("service_type", "method_names"),
    [
        (
            HouseholdService,
            ("get_household", "create_household", "update_household"),
        ),
        (PolicyService, ("get_policy", "get_policy_json", "set_policy")),
        (
            SimulationService,
            (
                "get_or_create_simulation",
                "get_simulation",
                "update_simulation",
            ),
        ),
        (UserService, ("get_profile", "create_profile", "update_profile")),
    ],
)
def test_core_service_public_methods_do_not_accept_sessions(
    service_type,
    method_names,
):
    for method_name in method_names:
        parameters = inspect.signature(getattr(service_type, method_name)).parameters
        assert "session" not in parameters
        assert "session_factory" not in parameters


@pytest.mark.parametrize(
    "module_name",
    [
        "household_routes.py",
        "policy_routes.py",
        "simulation_routes.py",
        "user_profile_routes.py",
    ],
)
def test_core_routes_do_not_manage_sessions(module_name):
    source = (ROUTE_ROOT / module_name).read_text(encoding="utf-8")
    assert "get_v1_session_factory" not in source
    assert "sqlalchemy" not in source


def test_core_services_commit_writes_and_return_generated_ids(
    orm_session_factory,
    monkeypatch,
):
    monkeypatch.setattr(
        "policyengine_api.services.household_service.hash_object",
        lambda value: "household-hash",
    )
    service = HouseholdService(orm_session_factory)

    household = service.create_household(
        "us",
        {"people": {"you": {"age": {"2026": 40}}}},
        "Service-owned transaction",
    )

    assert household.id is not None
    with orm_session_factory() as session:
        stored = session.get(Household, household.id)
        assert stored is not None
        assert stored.household_json == {"people": {"you": {"age": {"2026": 40}}}}


def test_core_services_roll_back_failed_writes(
    orm_session_factory,
    monkeypatch,
):
    monkeypatch.setattr(
        "policyengine_api.services.household_service.hash_object",
        lambda value: "household-hash",
    )
    session_type = orm_session_factory.class_
    original_flush = session_type.flush

    def fail_after_flush(session, *args, **kwargs):
        original_flush(session, *args, **kwargs)
        raise RuntimeError("forced failure")

    monkeypatch.setattr(session_type, "flush", fail_after_flush)
    service = HouseholdService(orm_session_factory)

    with pytest.raises(RuntimeError, match="forced failure"):
        service.create_household("us", {}, "Rolled back")

    monkeypatch.setattr(session_type, "flush", original_flush)
    with orm_session_factory() as session:
        count = session.scalar(select(func.count()).select_from(Household))
    assert count == 0
