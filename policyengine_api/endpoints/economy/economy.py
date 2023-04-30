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

# We'll keep the 10 most recent {job_id: {start_time, end_time}} in memory so we can track the average completion time.
RECENT_JOBS = {}

def get_average_time():
    """Get the average time for the last 10 jobs. Jobs might not have an end time (None)."""
    recent_jobs = [job for job in RECENT_JOBS.values() if job["end_time"]]
    # Get 10 most recently finishing jobs
    recent_jobs = sorted(recent_jobs, key=lambda x: x["end_time"], reverse=True)[:10]
    print(recent_jobs, RECENT_JOBS)
    if not recent_jobs:
        return 100
    total_time = sum(
        [
            (job["end_time"] - job["start_time"]).total_seconds()
            for job in recent_jobs
        ]
    )
    return total_time / len(recent_jobs)


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
    print(f"Got request for {country_id} {policy_id} {baseline_policy_id}")
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

    print("Checking if already calculated")

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
        if seconds_elapsed > 400:
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
        RECENT_JOBS[job_id] = dict(start_time=datetime.datetime.now(), end_time=None)
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
        print("Enqueuing job")
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
            if job_id in RECENT_JOBS and RECENT_JOBS[job_id].get("end_time") is None and result["status"] != "computing":
                RECENT_JOBS[job_id]["end_time"] = datetime.datetime.now()
            result["reform_impact_json"] = json.loads(
                result["reform_impact_json"]
            )
            return dict(
                status=result["status"],
                average_time=get_average_time(),
                message=None,
                result=result["reform_impact_json"],
            )
        # Otherwise, return the first one
        result = result[0]
        # If there are >100 jobs in the RECENT_JOBS dict, remove the oldest one
        if len(RECENT_JOBS) > 100:
            oldest_job_id = min(RECENT_JOBS, key=lambda k: RECENT_JOBS[k]["start_time"])
            del RECENT_JOBS[oldest_job_id]
        job = Job.fetch(job_id, connection=queue.connection)
        return dict(
            status=result["status"],
            message=f"Your position in the queue is {job.get_position()}.",
            average_time=get_average_time(),
            time_elapsed = (datetime.datetime.now() - RECENT_JOBS[job_id]["start_time"]).total_seconds(),
            result=result["reform_impact_json"],
        )
