import pytest
import json
from types import SimpleNamespace

from policyengine_api.constants import POLICYENGINE_VERSION
from policyengine_api.data.v1_models import Household, Policy
from policyengine_api.runtime_cache.core import CacheNamespace
from policyengine_api.runtime_cache.fake import InMemoryCacheBackend
from policyengine_api.runtime_cache.household_traces import (
    HouseholdTraceCache,
    HouseholdTraceIdentity,
    HouseholdTraceValue,
)

valid_tracer = {
    "tracer_output": [
        "only_government_benefit <1500>",
        "    market_income <1000>",
        "        employment_income <1000>",
        "            main_employment_income <1000>",
        "    non_market_income <500>",
        "        pension_income <500>",
    ]
}

valid_tracer_row = {
    "household_id": "71424",
    "policy_id": "2",
    "country_id": "us",
    "api_version": "1.150.0",
    "tracer_output": json.dumps(valid_tracer["tracer_output"]),
}


@pytest.fixture
def test_tracer_data(orm_session_factory):
    with orm_session_factory.begin() as session:
        session.add_all(
            [
                Household(
                    id=int(valid_tracer_row["household_id"]),
                    country_id=valid_tracer_row["country_id"],
                    label=None,
                    api_version=valid_tracer_row["api_version"],
                    household_json={},
                    household_hash="household-hash",
                ),
                Policy(
                    id=int(valid_tracer_row["policy_id"]),
                    country_id=valid_tracer_row["country_id"],
                    label=None,
                    api_version=valid_tracer_row["api_version"],
                    policy_json={},
                    policy_hash="policy-hash",
                ),
            ]
        )
    cache = HouseholdTraceCache(
        InMemoryCacheBackend(),
        CacheNamespace("test", "api"),
    )
    cache.set(
        HouseholdTraceIdentity(
            household_id=int(valid_tracer_row["household_id"]),
            policy_id=int(valid_tracer_row["policy_id"]),
            country_id=valid_tracer_row["country_id"],
            household_hash="household-hash",
            policy_hash="policy-hash",
            country_package_version=valid_tracer_row["api_version"],
            policyengine_version=POLICYENGINE_VERSION,
        ),
        HouseholdTraceValue(
            household={},
            tracer_output=json.loads(valid_tracer_row["tracer_output"]),
        ),
    )
    return SimpleNamespace(
        household_id=int(valid_tracer_row["household_id"]),
        policy_id=int(valid_tracer_row["policy_id"]),
        country_id=valid_tracer_row["country_id"],
        api_version=valid_tracer_row["api_version"],
        cache=cache,
    )
