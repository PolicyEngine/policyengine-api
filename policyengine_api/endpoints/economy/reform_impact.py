import flask
import json
from policyengine_api.constants import (
    COUNTRY_PACKAGE_VERSIONS,
)
from policyengine_api.country import PolicyEngineCountry, create_policy_reform
from policyengine_api.endpoints.policy import (
    get_current_law_policy_id,
)
from policyengine_api.data import PolicyEngineDatabase, database
from .compare import compare_economic_outputs
from .single_economy import compute_economy
from .analysis import trigger_policy_analysis
from policyengine_api.utils import hash_object
from datetime import datetime

def ensure_economy_computed(
    country_id: str,
    policy_id: str,
    region: str,
    time_period: str,
    options: dict,
):
    options_hash = hash_object(json.dumps(options))
    api_version = COUNTRY_PACKAGE_VERSIONS[country_id]
    print("Checking if already calculated")
    economy = database.query(
        f"SELECT policy_id FROM economy WHERE country_id = ? AND policy_id = ? AND region = ? AND time_period = ? AND options_hash = ? AND api_version = ?",
        (country_id, policy_id, region, time_period, options_hash, api_version),
    ).fetchone()
    if economy is None:
        try:
            print("Calculating economy")
            economy_result = compute_economy(
                country_id,
                policy_id,
                region=region,
                time_period=time_period,
                options=options,
            )
            print("Saving economy")
            database.query(
                f"INSERT INTO economy (policy_id, country_id, region, time_period, options_hash, api_version, economy_json, status, options_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    int(policy_id),
                    country_id,
                    region,
                    time_period,
                    options_hash,
                    api_version,
                    json.dumps(economy_result),
                    "ok",
                    json.dumps(options),
                ),
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
        except Exception as e:
            database.query(
                f"INSERT INTO economy (economy_json, status, message, options_json, country_id, policy_id, region, time_period, options_hash, api_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    json.dumps({}),
                    "error",
                    str(e)[:250],
                    json.dumps(options),
                    country_id,
                    policy_id,
                    region,
                    time_period,
                    options_hash,
                    api_version,
                )
            )
            return dict(
                policy_id=policy_id,
                country_id=country_id,
                region=region,
                time_period=time_period,
                options_hash=options_hash,
                api_version=api_version,
                economy_json=json.dumps({}),
                status="error",
                message=str(e)[:250],
            )
    else:
        # Now get the total object now we know it exists
        economy = database.query(
            f"SELECT * FROM economy WHERE country_id = ? AND policy_id = ? AND region = ? AND time_period = ? AND options_hash = ? AND api_version = ?",
            (country_id, policy_id, region, time_period, options_hash, api_version),
        ).fetchone()
        economy = dict(economy)
        economy["economy_json"] = json.loads(economy["economy_json"])
        economy["options_json"] = json.loads(economy["options_json"])
        return economy


def set_reform_impact_data(
    baseline_policy_id: int,
    policy_id: int,
    country_id: str,
    region: str,
    time_period: str,
    options: dict,
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
    try:
        options_hash = json.dumps(options, sort_keys=True)
        baseline_policy_id = int(baseline_policy_id)
        policy_id = int(policy_id)
        print("getting baseline economy")
        baseline_economy = ensure_economy_computed(
            country_id,
            baseline_policy_id,
            region,
            time_period,
            options,
        )
        print("getting reform economy")
        reform_economy = ensure_economy_computed(
            country_id,
            policy_id,
            region,
            time_period,
            options,
        )
        print("comparing economies")
        if (
            baseline_economy["status"] != "ok"
            or reform_economy["status"] != "ok"
        ):
            database.query(
                "INSERT INTO reform_impact (country_id, reform_policy_id, baseline_policy_id, region, time_period, options_hash, reform_impact_json, status, message, api_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    country_id,
                    policy_id,
                    baseline_policy_id,
                    region,
                    time_period,
                    options_hash,
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
                    "error",
                    "Error computing baseline or reform economy.",
                    COUNTRY_PACKAGE_VERSIONS[country_id],
                ),
            )
        else:
            baseline_economy = baseline_economy["economy_json"]
            reform_economy = reform_economy["economy_json"]
            impact = compare_economic_outputs(baseline_economy, reform_economy)
            print("inserting into database")
            # Delete all reform impact rows with the same baseline and reform policy IDs

            query = (
                "DELETE FROM reform_impact WHERE country_id = ? AND "
                "reform_policy_id = ? AND baseline_policy_id = ? AND "
                "region = ? AND time_period = ? AND options_hash = ? AND "
                "status = 'computing'"
            )

            database.query(
                query,
                country_id,
                policy_id,
                baseline_policy_id,
                region,
                time_period,
                options_hash,
            )

            # Insert into table

            query = (
                "INSERT INTO reform_impact (country_id, reform_policy_id, "
                "baseline_policy_id, region, time_period, options_hash, "
                "options_json, reform_impact_json, status, start_time, api_version) VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            )

            database.query(
                query,
                country_id,
                policy_id,
                baseline_policy_id,
                region,
                time_period,
                options_hash,
                json.dumps(options),
                json.dumps(impact),
                "ok",
                datetime.strftime(datetime.now(), "%Y-%m-%d %H:%M:%S.%f"),
                COUNTRY_PACKAGE_VERSIONS[country_id],
            )
    except Exception as e:
        pass
