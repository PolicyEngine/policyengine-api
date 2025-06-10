from policyengine_api.services.policy_service import PolicyService
from policyengine_api.services.job_service import JobService
from policyengine_api.services.reform_impacts_service import (
    ReformImpactsService,
)
from policyengine_api.data import local_database, database
import json
import datetime

policy_service = PolicyService()
job_service = JobService()
reform_impacts_service = ReformImpactsService()


class EconomyService:
    """
    Service for calculating economic impact of policy reforms; this is connected
    to the /economy route, which does not have its own table; therefore, it connects
    with other services to access their respective tables
    """

    def get_economic_impact(
        self,
        country_id: str,
        policy_id: int,
        baseline_policy_id: int,
        region: str,
        dataset: str,
        time_period: str,
        options: dict,
        api_version: str,
        run_api_v1: bool = False,
    ):
        """
        Calculate the society-wide economic impact of a policy reform.
        """
        try:
            # Note for anyone modifying options_hash: redis-queue treats ":" as a namespace
            # delimiter; don't use colons in options_hash
            options_hash = (
                "[" + "&".join([f"{k}={v}" for k, v in options.items()]) + "]"
            )
            print("Checking if already calculated")

            # Create job ID
            job_id = f"reform_impact_{country_id}_{policy_id}_{baseline_policy_id}_{region}_{dataset}_{time_period}_{options_hash}_{api_version}"

            # First, check if already calculated
            print("Checking previous impacts...")
            previous_impacts = self._get_previous_impacts(
                country_id,
                policy_id,
                baseline_policy_id,
                region,
                dataset,
                time_period,
                options_hash,
                api_version,
            )
            print(f"Found {len(previous_impacts)} previous impacts")
            print(
                f"Previous impacts status: {[imp.get('status') for imp in previous_impacts]}"
            )
            if len(previous_impacts) == 0:

                # Add job to recent job list
                print("No previous impacts found, creating new job...")
                job_service.add_recent_job(
                    job_id=job_id,
                    type="calculate_economy_simulation",
                    start_time=datetime.datetime.now(datetime.timezone.utc),
                    end_time=None,
                )

                # Add computing record
                self._set_impact_computing(
                    country_id,
                    policy_id,
                    baseline_policy_id,
                    region,
                    dataset,
                    time_period,
                    options,
                    options_hash,
                    api_version,
                )

                # Get baseline and reform policy
                print("Fetching baseline and reform policies")
                baseline_policy = policy_service.get_policy_json(
                    country_id, baseline_policy_id
                )
                reform_policy = policy_service.get_policy_json(
                    country_id, policy_id
                )

                # Enqueue job
                print("Enqueuing job")
                job_service.execute_job(
                    type="calculate_economy_simulation",
                    baseline_policy_id=baseline_policy_id,
                    policy_id=policy_id,
                    country_id=country_id,
                    region=region,
                    dataset=dataset,
                    time_period=time_period,
                    options=options,
                    baseline_policy=baseline_policy,
                    reform_policy=reform_policy,
                    job_id=job_id,
                    job_timeout=20 * 60,
                    run_api_v1=run_api_v1,
                )

                # Return computing status
                return (
                    dict(
                        status="computing",
                        message="Calculating economic impact. Please try again in a few seconds.",
                        result=None,
                    ),
                    200,
                )
            else:
                print(
                    f"Found previous impacts, first status: {previous_impacts[0]['status']}"
                )
                ok_results = [
                    r
                    for r in previous_impacts
                    if r["status"] in ["ok", "error"]
                ]
                if len(ok_results) > 0:
                    result = ok_results[0]
                    result = dict(result)

                    recent_jobs = job_service.get_recent_jobs()
                    if (
                        job_id in recent_jobs
                        and recent_jobs[job_id].get("end_time") is None
                        and result["status"] != "computing"
                    ):
                        job_service.update_recent_job(
                            job_id,
                            "end_time",
                            datetime.datetime.now(datetime.timezone.utc),
                        )

                    result["reform_impact_json"] = json.loads(
                        result["reform_impact_json"]
                    )
                    return (
                        dict(
                            status=result["status"],
                            average_time=job_service.get_average_time(),
                            message=None,
                            result=result["reform_impact_json"],
                        ),
                        200,
                    )
                computing_result = previous_impacts[0]

                queue_pos = job_service.fetch_job_queue_pos(job_id)
                return (
                    dict(
                        status=computing_result["status"],
                        queue_position=queue_pos,
                        average_time=job_service.get_average_time(),
                        result=computing_result["reform_impact_json"],
                    ),
                    200,
                )

        except Exception as e:
            print(f"Error getting economic impact: {str(e)}")
            raise e

    def _get_previous_impacts(
        self,
        country_id: str,
        policy_id: int,
        baseline_policy_id: int,
        region: str,
        dataset: str,
        time_period: str,
        options_hash: str,
        api_version: str,
    ):
        """
        Fetch any previous simulation runs for the given policy reform.
        """

        previous_impacts = reform_impacts_service.get_all_reform_impacts(
            country_id,
            policy_id,
            baseline_policy_id,
            region,
            dataset,
            time_period,
            options_hash,
            api_version,
        )
        previous_impacts = [
            dict(
                reform_impact_json=r["reform_impact_json"],
                status=r["status"],
                start_time=r["start_time"],
            )
            for r in previous_impacts
        ]
        return previous_impacts

    def _set_impact_computing(
        self,
        country_id: str,
        policy_id: int,
        baseline_policy_id: int,
        region: str,
        dataset: str,
        time_period: str,
        options: dict,
        options_hash: str,
        api_version: str,
    ):
        """
        In the reform_impact table, set the status of the impact to "computing".
        """
        try:
            reform_impacts_service.set_reform_impact(
                country_id,
                policy_id,
                baseline_policy_id,
                region,
                dataset,
                time_period,
                json.dumps(options),
                options_hash,
                "computing",
                api_version,
                json.dumps({}),
                datetime.datetime.now(),
            )
        except Exception as e:
            print(f"Error inserting computing record: {str(e)}")
            raise e
