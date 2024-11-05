import flask
import json
from policyengine_api.constants import (
    COUNTRY_PACKAGE_VERSIONS,
)
from policyengine_api.country import PolicyEngineCountry, create_policy_reform
from policyengine_api.endpoints.policy import (
    get_current_law_policy_id,
)
from policyengine_api.data import PolicyEngineDatabase, local_database
from .compare import compare_economic_outputs
from .single_economy import compute_economy
from policyengine_api.utils import hash_object
from datetime import datetime
import traceback
from rq import Queue
from rq.job import Job
from redis import Redis
import time

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


def set_reform_impact_data(
    baseline_policy_id: int,
    policy_id: int,
    country_id: str,
    region: str,
    time_period: str,
    options: dict,
    baseline_policy: dict,
    reform_policy: dict,
):
    options_hash = json.dumps(options, sort_keys=True)
    baseline_policy_id = int(baseline_policy_id)
    policy_id = int(policy_id)
    try:
        set_reform_impact_data_routine(
            baseline_policy_id,
            policy_id,
            country_id,
            region,
            time_period,
            options,
            baseline_policy,
            reform_policy,
        )
    except Exception as e:
        # Save the status as error and the message as the error message
        local_database.query(
            "UPDATE reform_impact SET status = ?, message = ?, end_time = ? WHERE country_id = ? AND reform_policy_id = ? AND baseline_policy_id = ? AND region = ? AND time_period = ? AND options_hash = ?",
            (
                "error",
                traceback.format_exc(),
                datetime.strftime(datetime.now(), "%Y-%m-%d %H:%M:%S.%f"),
                country_id,
                policy_id,
                baseline_policy_id,
                region,
                time_period,
                options_hash,
            ),
        )
        raise e


def set_reform_impact_data_routine(
    baseline_policy_id: int,
    policy_id: int,
    country_id: str,
    region: str,
    time_period: str,
    options: dict,
    baseline_policy: dict,
    reform_policy: dict,
) -> None:
    """
    Synchronously computes the reform impact for a given policy and country.

    Args:
        database (PolicyEngineDatabase): The database.
        baseline_policy_id (int): The baseline policy ID.
        policy_id (int): The policy ID.
        country_id (str): The country ID. Currently supported countries are the UK and the US.
        region (str): The region to filter on.
        time_period (str): The time period, e.g. 2024.
        options (dict): Any additional options.
    """
    options_hash = json.dumps(options, sort_keys=True)
    baseline_policy_id = int(baseline_policy_id)
    policy_id = int(policy_id)
    identifiers = (
        country_id,
        policy_id,
        baseline_policy_id,
        region,
        time_period,
        options_hash,
    )
    query = (
        "DELETE FROM reform_impact WHERE country_id = ? AND "
        "reform_policy_id = ? AND baseline_policy_id = ? AND "
        "region = ? AND time_period = ? AND options_hash = ? AND "
        "status = 'computing'"
    )

    local_database.query(
        query,
        (
            country_id,
            policy_id,
            baseline_policy_id,
            region,
            time_period,
            options_hash,
        ),
    )

    # Insert into table

    query = (
        "INSERT INTO reform_impact (country_id, reform_policy_id, "
        "baseline_policy_id, region, time_period, options_hash, "
        "options_json, reform_impact_json, status, start_time, api_version) VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )

    local_database.query(
        query,
        (
            country_id,
            policy_id,
            baseline_policy_id,
            region,
            time_period,
            options_hash,
            json.dumps(options),
            json.dumps({}),
            "computing",
            datetime.strftime(datetime.now(), "%Y-%m-%d %H:%M:%S.%f"),
            COUNTRY_PACKAGE_VERSIONS[country_id],
        ),
    )
    comment = lambda x: set_comment_on_job(x, *identifiers)

    baseline_economy = queue.enqueue(
        compute_economy,
        country_id=country_id,
        policy_id=baseline_policy_id,
        region=region,
        time_period=time_period,
        options=options,
        policy_json=baseline_policy,
    )
    reform_economy = queue.enqueue(
        compute_economy,
        country_id=country_id,
        policy_id=policy_id,
        region=region,
        time_period=time_period,
        options=options,
        policy_json=reform_policy,
    )
    while not baseline_economy.is_finished or baseline_economy.is_failed:
        time.sleep(1)
    while not reform_economy.is_finished or reform_economy.is_failed:
        time.sleep(1)
    baseline_economy = baseline_economy.result
    reform_economy = reform_economy.result
    if baseline_economy.is_failed:
        baseline_economy.result = {
            "status": "error",
            "message": "Error computing baseline economy.",
        }
    if reform_economy.is_failed:
        reform_economy.result = {
            "status": "error",
            "message": "Error computing reform economy.",
        }
    if baseline_economy["status"] != "ok" or reform_economy["status"] != "ok":
        local_database.query(
            "UPDATE reform_impact SET status = ?, message = ?, end_time = ?, reform_impact_json = ? WHERE country_id = ? AND reform_policy_id = ? AND baseline_policy_id = ? AND region = ? AND time_period = ? AND options_hash = ?",
            (
                "error",
                "Error computing baseline or reform economy.",
                datetime.strftime(datetime.now(), "%Y-%m-%d %H:%M:%S.%f"),
                json.dumps(
                    dict(
                        country_id=country_id,
                        region=region,
                        time_period=time_period,
                        options=options,
                        baseline_economy=baseline_economy,
                        reform_economy=reform_economy,
                    )
                ),
                country_id,
                policy_id,
                baseline_policy_id,
                region,
                time_period,
                options_hash,
            ),
        )
    else:
        baseline_economy = baseline_economy["result"]
        reform_economy = reform_economy["result"]
        comment("Comparing baseline and reform")
        impact = compare_economic_outputs(
            baseline_economy, reform_economy, country_id=country_id
        )
        # Delete all reform impact rows with the same baseline and reform policy IDs
        local_database.query(
            "UPDATE reform_impact SET status = ?, message = ?, end_time = ?, reform_impact_json = ? WHERE country_id = ? AND reform_policy_id = ? AND baseline_policy_id = ? AND region = ? AND time_period = ? AND options_hash = ?",
            (
                "ok",
                "Completed",
                datetime.strftime(datetime.now(), "%Y-%m-%d %H:%M:%S.%f"),
                json.dumps(impact),
                country_id,
                policy_id,
                baseline_policy_id,
                region,
                time_period,
                options_hash,
            ),
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
