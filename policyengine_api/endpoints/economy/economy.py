from policyengine_api.country import validate_country, COUNTRIES
from policyengine_api.endpoints.policy import get_current_law_policy_id
from policyengine_api.utils import hash_object
from policyengine_api.data import database, local_database
from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from .reform_impact import set_reform_impact_data
from flask import request
import json
from rq import Queue
from rq.job import Job
from redis import Redis
import datetime

queue = Queue(connection=Redis())


def get_economic_impact(
    country_id: str, policy_id: str, baseline_policy_id: str = None
):
    """Calculate the economic impact of a policy.

    Args:
        country_id (str): The country ID.
        policy_id (str): The policy ID.
        baseline_policy_id (str): The baseline policy ID.

    Returns:
        dict: The economic impact.
    """
    invalid_country = validate_country(country_id)
    if invalid_country:
        return invalid_country

    country = COUNTRIES.get(country_id)

    policy_id = int(policy_id or get_current_law_policy_id(country_id))
    baseline_policy_id = int(
        baseline_policy_id or get_current_law_policy_id(country_id)
    )

    default_region = country.metadata["result"]["economy_options"]["region"][
        0
    ]["name"]
    default_time_period = country.metadata["result"]["economy_options"][
        "time_period"
    ][0]["name"]

    query_parameters = request.args
    options = dict(query_parameters)
    options = json.loads(json.dumps(options))
    region = options.pop("region", default_region)
    time_period = options.pop("time_period", default_time_period)
    api_version = options.pop(
        "version", COUNTRY_PACKAGE_VERSIONS.get(country_id)
    )
    options_hash = json.dumps(options, sort_keys=True)

    # First, check if already calculated
    result = local_database.query(
        f"SELECT reform_impact_json, status, start_time FROM reform_impact WHERE country_id = ? AND reform_policy_id = ? AND baseline_policy_id = ? AND region = ? AND time_period = ? AND options_hash = ? AND api_version = ?",
        (
            country_id,
            policy_id,
            baseline_policy_id,
            region,
            time_period,
            options_hash,
            api_version,
        ),
    ).fetchall()

    # If there is a computing record which started more than 2 minutes ago, restart the job
    result = [
        dict(
            reform_impact_json=r[0],
            status=r[1],
            start_time=r[2],
        )
        for r in result
    ]
    computing_results = [r for r in result if r["status"] == "computing"]
    restarting = False
    if len(computing_results) > 0:
        computing_result = computing_results[0]
        start_date = datetime.datetime.strptime(
            computing_result["start_time"], "%Y-%m-%d %H:%M:%S.%f"
        )
        seconds_elapsed = (
            datetime.datetime.now() - start_date
        ).total_seconds()
        if seconds_elapsed > 120:
            print(
                f"Restarting computing job because it started {seconds_elapsed} seconds ago"
            )
            restarting = True
            # Delete the computing record
            local_database.query(
                f"DELETE FROM reform_impact WHERE country_id = ? AND reform_policy_id = ? AND baseline_policy_id = ? AND region = ? AND time_period = ? AND options_hash = ? AND api_version = ?",
                (
                    country_id,
                    policy_id,
                    baseline_policy_id,
                    region,
                    time_period,
                    options_hash,
                    api_version,
                ),
            )

    job_id = f"reform_impact_{country_id}_{policy_id}_{baseline_policy_id}_{region}_{time_period}_{options_hash}_{api_version}"

    if len(result) == 0 or restarting:
        # First, add a 'computing' record
        local_database.query(
            f"INSERT INTO reform_impact (country_id, reform_policy_id, baseline_policy_id, region, time_period, options_json, options_hash, status, api_version, reform_impact_json, start_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                country_id,
                policy_id,
                baseline_policy_id,
                region,
                time_period,
                json.dumps(options),
                options_hash,
                "computing",
                api_version,
                json.dumps({}),
                datetime.datetime.now(),
            ),
        )
        baseline_policy = database.query(
            "SELECT policy_json FROM policy WHERE country_id = ? AND id = ?",
            (country_id, baseline_policy_id),
        ).fetchone()[0]
        reform_policy = database.query(
            "SELECT policy_json FROM policy WHERE country_id = ? AND id = ?",
            (country_id, policy_id),
        ).fetchone()[0]
        queue.enqueue(
            set_reform_impact_data,
            baseline_policy_id,
            policy_id,
            country_id,
            region,
            time_period,
            options,
            baseline_policy,
            reform_policy,
            job_id=job_id,
        )
        return dict(
            status="computing",
            message="Calculating economic impact. Please try again in a few seconds.",
            result=None,
        )
    else:
        # If there is one with status "ok" or "error", return that one
        ok_results = [r for r in result if r["status"] in ["ok", "error"]]
        if len(ok_results) > 0:
            result = ok_results[0]
            result = dict(result)
            result["reform_impact_json"] = json.loads(
                result["reform_impact_json"]
            )
            return dict(
                status=result["status"],
                message=None,
                result=result["reform_impact_json"],
            )
        # Otherwise, return the first one
        result = result[0]
        job = Job.fetch(job_id, connection=queue.connection)
        return dict(
            status=result["status"],
            message=f"Your position in the queue is {job.get_position()}.",
            result=result["reform_impact_json"],
        )
