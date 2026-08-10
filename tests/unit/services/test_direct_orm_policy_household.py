from sqlalchemy import select

from policyengine_api.data.v1_models import Household, Policy
from policyengine_api.services.household_service import HouseholdService
from policyengine_api.services.policy_service import PolicyService


def test_policy_service_reads_and_writes_mapped_models(
    orm_session_factory,
    monkeypatch,
):
    monkeypatch.setattr(
        "policyengine_api.services.policy_service.hash_object",
        lambda value: "policy-hash",
    )
    service = PolicyService(orm_session_factory)

    policy_id, message, existed = service.set_policy(
        "us",
        "Direct ORM policy",
        {"gov.example.rate": {"2026": 0.2}},
    )
    policy = service.get_policy("us", policy_id)

    assert isinstance(policy, Policy)
    assert policy.policy_json == {"gov.example.rate": {"2026": 0.2}}
    assert message == "Policy created"
    assert existed is False


def test_household_service_reads_updates_and_writes_mapped_models(
    orm_session_factory,
    monkeypatch,
):
    monkeypatch.setattr(
        "policyengine_api.services.household_service.hash_object",
        lambda value: "household-hash",
    )
    service = HouseholdService(orm_session_factory)
    payload = {"people": {"you": {"age": {"2026": 40}}}}

    household = service.create_household(
        "us",
        payload,
        "Direct ORM household",
    )
    with orm_session_factory() as session:
        stored = session.scalar(
            select(Household).where(Household.id == household.id)
        )

    assert household.id == stored.id
    assert stored.household_json == payload

    updated = service.update_household(
        "us",
        stored.id,
        {"people": {"you": {"age": {"2026": 41}}}},
        "Updated",
    )

    assert isinstance(updated, Household)
    assert updated.label == "Updated"
    assert updated.household_json["people"]["you"]["age"]["2026"] == 41
