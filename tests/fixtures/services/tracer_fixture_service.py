import pytest
import json
from policyengine_api.data.v1_models import Tracer

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
def test_tracer_data(orm_session):
    tracer = Tracer(
        household_id=int(valid_tracer_row["household_id"]),
        policy_id=int(valid_tracer_row["policy_id"]),
        country_id=valid_tracer_row["country_id"],
        api_version=valid_tracer_row["api_version"],
        tracer_output=json.loads(valid_tracer_row["tracer_output"]),
    )
    orm_session.add(tracer)
    orm_session.commit()
    return tracer
