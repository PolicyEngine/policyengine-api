from policyengine_api.data import local_database
import datetime


class ReformImpactsService:
    """
    Service for storing and retrieving economy-wide reform impacts;
    this is connected to the locally-stored reform_impact table
    and no existing route
    """

    def get_all_reform_impacts(
        self,
        country_id,
        policy_id,
        baseline_policy_id,
        region,
        time_period,
        options_hash,
        api_version,
    ):
        try:
            query = (
                "SELECT reform_impact_json, status, message, start_time FROM "
                "reform_impact WHERE country_id = ? AND reform_policy_id = ? AND "
                "baseline_policy_id = ? AND region = ? AND time_period = ? AND "
                "options_hash = ? AND api_version = ?"
            )
            return local_database.query(
                query,
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
        except Exception as e:
            print(f"Error getting all reform impacts: {str(e)}")
            raise e

    def set_reform_impact(
        self,
        country_id,
        policy_id,
        baseline_policy_id,
        region,
        time_period,
        options,
        options_hash,
        status,
        api_version,
        reform_impact_json,
        start_time,
    ):
        try:
            query = (
                "INSERT INTO reform_impact (country_id, reform_policy_id, baseline_policy_id, "
                "region, time_period, options_json, options_hash, status, api_version, "
                "reform_impact_json, start_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            )
            local_database.query(
                query,
                (
                    country_id,
                    policy_id,
                    baseline_policy_id,
                    region,
                    time_period,
                    options,
                    options_hash,
                    status,
                    api_version,
                    reform_impact_json,
                    start_time,
                ),
            )
        except Exception as e:
            print(f"Error setting reform impact: {str(e)}")
            raise e

    def delete_reform_impact(
        self,
        country_id,
        policy_id,
        baseline_policy_id,
        region,
        time_period,
        options_hash,
    ):
        try:
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
        except Exception as e:
            print(f"Error deleting reform impact: {str(e)}")
            raise e

    def set_error_reform_impact(
        self,
        country_id,
        policy_id,
        baseline_policy_id,
        region,
        time_period,
        options_hash,
        message,
    ):
        try:
            query = (
                "UPDATE reform_impact SET status = ?, message = ?, end_time = ? WHERE "
                "country_id = ? AND reform_policy_id = ? AND baseline_policy_id = ? AND "
                "region = ? AND time_period = ? AND options_hash = ?"
            )
            local_database.query(
                query,
                (
                    "error",
                    message,
                    datetime.datetime.strftime(
                        datetime.datetime.now(datetime.timezone.utc),
                        "%Y-%m-%d %H:%M:%S.%f",
                    ),
                    country_id,
                    policy_id,
                    baseline_policy_id,
                    region,
                    time_period,
                    options_hash,
                ),
            )
        except Exception as e:
            print(
                f"Error setting error reform impact (something must be REALLY wrong): {str(e)}"
            )
            raise e

    def set_complete_reform_impact(
        self,
        country_id,
        reform_policy_id,
        baseline_policy_id,
        region,
        time_period,
        options_hash,
        reform_impact_json,
    ):
        try:
            query = (
                "UPDATE reform_impact SET status = ?, message = ?, end_time = ?, "
                "reform_impact_json = ? WHERE country_id = ? AND reform_policy_id = ? AND "
                "baseline_policy_id = ? AND region = ? AND time_period = ? AND options_hash = ?"
            )
            local_database.query(
                query,
                (
                    "ok",
                    "Completed",
                    datetime.datetime.strftime(
                        datetime.datetime.now(datetime.timezone.utc),
                        "%Y-%m-%d %H:%M:%S.%f",
                    ),
                    reform_impact_json,
                    country_id,
                    reform_policy_id,
                    baseline_policy_id,
                    region,
                    time_period,
                    options_hash,
                ),
            )
        except Exception as e:
            print(f"Error setting completed reform impact: {str(e)}")
            raise e
