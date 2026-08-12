import inspect
from pathlib import Path

from policyengine_api.data.v1_models import UserPolicy
from policyengine_api.services.user_policy_service import (
    UserPolicyCreateResult,
    UserPolicyService,
)


ROUTE_PATH = (
    Path(__file__).parents[3] / "policyengine_api" / "routes" / "policy_routes.py"
)


def _values(**overrides):
    values = {
        "country_id": "us",
        "reform_id": 2,
        "reform_label": "Reform",
        "baseline_id": 1,
        "baseline_label": "Current law",
        "user_id": "auth0|one",
        "year": "2026",
        "geography": "us",
        "dataset": "enhanced_cps_2024",
        "number_of_provisions": 3,
        "api_version": "1",
        "added_date": 1,
        "updated_date": 2,
        "budgetary_impact": None,
        "type": None,
    }
    values.update(overrides)
    return values


def test_user_policy_public_methods_do_not_accept_sessions():
    for method_name in (
        "create_or_get_user_policy",
        "list_user_policies",
        "update_user_policy",
    ):
        parameters = inspect.signature(
            getattr(UserPolicyService, method_name)
        ).parameters
        assert "session" not in parameters
        assert "session_factory" not in parameters


def test_policy_routes_do_not_manage_sessions_or_queries():
    source = ROUTE_PATH.read_text(encoding="utf-8")
    assert "get_v1_session_factory" not in source
    assert "from sqlalchemy" not in source
    assert "select(" not in source


def test_create_reuse_list_and_update_user_policy(orm_session_factory):
    service = UserPolicyService(orm_session_factory)

    created = service.create_or_get_user_policy(_values())
    reused = service.create_or_get_user_policy(
        _values(number_of_provisions=99, updated_date=99)
    )
    listed = service.list_user_policies("us", "auth0|one")
    updated = service.update_user_policy(
        "us",
        created.user_policy.id,
        {"reform_label": "Updated", "updated_date": 3},
    )

    assert isinstance(created, UserPolicyCreateResult)
    assert created.created is True
    assert reused.created is False
    assert reused.user_policy.id == created.user_policy.id
    assert len(listed) == 1
    assert isinstance(listed[0], UserPolicy)
    assert updated.reform_label == "Updated"
    assert updated.updated_date == 3


def test_update_user_policy_requires_matching_country(orm_session_factory):
    service = UserPolicyService(orm_session_factory)
    created = service.create_or_get_user_policy(_values(country_id="uk"))

    assert (
        service.update_user_policy(
            "us",
            created.user_policy.id,
            {"reform_label": "Wrong country"},
        )
        is None
    )
    stored = service.list_user_policies("uk", "auth0|one")[0]
    assert stored.reform_label == "Reform"
