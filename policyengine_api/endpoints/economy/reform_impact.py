import json
from policyengine_api.constants import (
    COUNTRY_PACKAGE_VERSIONS,
)
from policyengine_api.data import local_database
from .single_economy import compute_economy
from policyengine_api.utils import hash_object
from rq import Queue
from redis import Redis

queue = Queue(connection=Redis())


def ensure_economy_computed(
    country_id: str,
    policy_id: str,
    region: str,
    time_period: str,
    options: dict,
    policy_json: dict,
):
    options_hash = hash_object(json.dumps(options))
    api_version = COUNTRY_PACKAGE_VERSIONS[country_id]
    economy_result = compute_economy(
        country_id,
        policy_id,
        region=region,
        time_period=time_period,
        options=options,
        policy_json=policy_json,
    )
    return dict(
        policy_id=policy_id,
        country_id=country_id,
        region=region,
        time_period=time_period,
        options_hash=options_hash,
        api_version=api_version,
        economy_json=economy_result,
        status="ok",
    )


def set_comment_on_job(
    comment: str,
    country_id,
    policy_id,
    baseline_policy_id,
    region,
    time_period,
    options_hash,
):
    local_database.query(
        "UPDATE reform_impact SET message = ? WHERE country_id = ? AND reform_policy_id = ? AND baseline_policy_id = ? AND region = ? AND time_period = ? AND options_hash = ?",
        (
            comment,
            country_id,
            policy_id,
            baseline_policy_id,
            region,
            time_period,
            options_hash,
        ),
    )
