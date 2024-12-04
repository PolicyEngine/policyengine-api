from policyengine_api.data import local_database
from policyengine_api.utils.logger import Logger
import datetime

logger = Logger()


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
        dataset,
        time_period,
        options_hash,
        api_version,
    ):
        logger.log(
            f"Getting all reform impacts for country {country_id}, policy {policy_id}, baseline {baseline_policy_id}, region {region}, dataset {dataset}"
        )
        try:
            query = (
                "SELECT reform_impact_json, status, message, start_time FROM "
                "reform_impact WHERE country_id = ? AND reform_policy_id = ? AND "
                "baseline_policy_id = ? AND region = ? AND time_period = ? AND "
                "options_hash = ? AND api_version = ? AND dataset = ?"
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
                    dataset,
                ),
            ).fetchall()
        except Exception as e:
            logger.error(f"Error getting all reform impacts: {str(e)}")
            raise e

    def set_reform_impact(
        self,
        country_id,
        policy_id,
        baseline_policy_id,
        region,
        dataset,
        time_period,
        options,
        options_hash,
        status,
        api_version,
        reform_impact_json,
        start_time,
    ):
        logger.log(
            f"Setting reform impact record for country {country_id}, policy {policy_id}, baseline {baseline_policy_id}, region {region}, dataset {dataset}"
        )
        try:
            query = (
                "INSERT INTO reform_impact (country_id, reform_policy_id, baseline_policy_id, "
                "region, dataset, time_period, options_json, options_hash, status, api_version, "
                "reform_impact_json, start_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            )
            local_database.query(
                query,
                (
                    country_id,
                    policy_id,
                    baseline_policy_id,
                    region,
                    dataset,
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
            logger.error(f"Error setting reform impact: {str(e)}")
            raise e

    def delete_reform_impact(
        self,
        country_id,
        policy_id,
        baseline_policy_id,
        region,
        dataset,
        time_period,
        options_hash,
    ):
        logger.log(
            f"Deleteing reform impact for country {country_id}, policy {policy_id}, baseline {baseline_policy_id}, region {region}, dataset {dataset}"
        )

        try:
            query = (
                "DELETE FROM reform_impact WHERE country_id = ? AND "
                "reform_policy_id = ? AND baseline_policy_id = ? AND "
                "region = ? AND time_period = ? AND options_hash = ? AND "
                "dataset = ? AND status = 'computing'"
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
                    dataset,
                ),
            )
        except Exception as e:
            logger.error(f"Error deleting reform impact: {str(e)}")
            raise e

    def set_error_reform_impact(
        self,
        country_id,
        policy_id,
        baseline_policy_id,
        region,
        dataset,
        time_period,
        options_hash,
        message,
    ):
        try:
            query = (
                "UPDATE reform_impact SET status = ?, message = ?, end_time = ? WHERE "
                "country_id = ? AND reform_policy_id = ? AND baseline_policy_id = ? AND "
                "region = ? AND time_period = ? AND options_hash = ? AND dataset = ?"
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
                    dataset,
                ),
            )
        except Exception as e:
            logger.error(
                f"Error setting error reform impact (something must be REALLY wrong): {str(e)}"
            )
            raise e

    def set_complete_reform_impact(
        self,
        country_id,
        reform_policy_id,
        baseline_policy_id,
        region,
        dataset,
        time_period,
        options_hash,
        reform_impact_json,
    ):
        logger.log("Setting completed reform impact")
        try:
            query = (
                "UPDATE reform_impact SET status = ?, message = ?, end_time = ?, "
                "reform_impact_json = ? WHERE country_id = ? AND reform_policy_id = ? AND "
                "baseline_policy_id = ? AND region = ? AND time_period = ? AND "
                "options_hash = ? AND dataset = ?"
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
                    dataset,
                ),
            )
        except Exception as e:
            logger.error(f"Error setting completed reform impact: {str(e)}")
            raise e
