"""
The Compute API is a separate Flask app that runs on a separate port. 
It is designed to be run on a separate server from the main PolicyEngine web app, so that it can
be used for compute-intensive tasks without affecting the main server.
"""

import flask
import requests
from flask_cors import CORS
import json
import threading
from policyengine_api.constants import (
    GET,
    POST,
    VERSION,
    COUNTRY_PACKAGE_VERSIONS,
)
from policyengine_api.country import PolicyEngineCountry
from policyengine_api.endpoints.policy import (
    create_policy_reform,
    get_current_law_policy_id,
)
from policyengine_api.data import PolicyEngineDatabase
from policyengine_api.compute_api.compare import compare_economic_outputs
from policyengine_api.compute_api.economy import compute_economy
from policyengine_api.utils import hash_object, safe_endpoint
from policyengine_api.logging import log
from typing import Callable
from datetime import datetime

app = application = flask.Flask(__name__)

CORS(app)

uk = PolicyEngineCountry("policyengine_uk")
us = PolicyEngineCountry("policyengine_us")
countries = dict(uk=uk, us=us)

database = PolicyEngineDatabase(local=False)


@app.route("/", methods=[GET])
def home():
    return f"<h1>PolicyEngine compute API v{VERSION}</h1><p>Use this API to compute the impact of public policy on economies.</p>"


@app.route("/compute", methods=[POST])
def compute() -> dict:
    log(
        api="compute",
        level="info",
        message="Received compute request",
    )
    json_body = flask.request.get_json()
    country_id = json_body.get("country_id")
    policy_id = int(json_body.get("policy_id"))
    baseline_policy_id = int(json_body.get("baseline_policy_id"))
    region = json_body.get("region")
    time_period = json_body.get("time_period")
    options = json_body.get("options")

    set_reform_impact_data(
        database,
        baseline_policy_id,
        policy_id,
        country_id,
        region,
        time_period,
        options,
    )

    return {"status": "ok"}


def ensure_economy_computed(
    country_id: str,
    policy_id: str,
    region: str,
    time_period: str,
    options: dict,
    economy_kwargs: dict,
):
    economy = database.get_in_table(
        "economy",
        policy_id=policy_id,
        **economy_kwargs,
    )
    if economy is None:
        try:
            economy_result = compute_economy(
                country_id,
                policy_id,
                region=region,
                time_period=time_period,
                options=options,
            )
            database.set_in_table(
                "economy",
                dict(
                    policy_id=int(policy_id),
                    **economy_kwargs,
                ),
                dict(
                    economy_json=json.dumps(economy_result),
                    status="ok",
                    options_json=json.dumps(options),
                ),
            )
        except Exception as e:
            database.set_in_table(
                "economy",
                dict(
                    policy_id=policy_id,
                    **economy_kwargs,
                ),
                dict(
                    economy_json=json.dumps({}),
                    status="error",
                    message=str(e)[:250],
                    options_json=json.dumps(options),
                ),
            )


def log_on_error(fn: Callable) -> Callable:
    def safe_fn(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            log(
                api="compute",
                level="error",
                message=str(e),
            )

    safe_fn.__name__ = fn.__name__
    return safe_fn


def set_reform_impact_data(
    database: PolicyEngineDatabase,
    baseline_policy_id: int,
    policy_id: int,
    country_id: str,
    region: str,
    time_period: str,
    options: dict,
) -> None:
    """
    Syncronously computes the reform impact for a given policy and country.

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
        options_hash = hash_object(json.dumps(options))
        economy_kwargs = dict(
            country_id=country_id,
            region=region,
            time_period=time_period,
            options_hash=options_hash,
            api_version=COUNTRY_PACKAGE_VERSIONS[country_id],
        )
        economy_arguments = region, time_period, options

        for required_policy_id in [baseline_policy_id, policy_id]:
            log(
                api="compute",
                level="info",
                message=f"Computing economy for policy {required_policy_id}",
            )
            ensure_economy_computed(
                country_id,
                int(required_policy_id),
                *economy_arguments,
                economy_kwargs=economy_kwargs,
            )

        baseline_economy = database.get_in_table(
            "economy",
            policy_id=baseline_policy_id,
            **economy_kwargs,
        )
        reform_economy = database.get_in_table(
            "economy",
            policy_id=policy_id,
            **economy_kwargs,
        )
        if (
            baseline_economy["status"] != "ok"
            or reform_economy["status"] != "ok"
        ):
            database.set_in_table(
                "reform_impact",
                dict(
                    **economy_kwargs,
                    baseline_policy_id=baseline_policy_id,
                    reform_policy_id=policy_id,
                ),
                dict(
                    reform_impact_json=json.dumps(
                        dict(
                            country_id=country_id,
                            region=region,
                            time_period=time_period,
                            options=options,
                            baseline_economy=baseline_economy,
                            reform_economy=reform_economy,
                        )
                    ),
                    status="error",
                    message="Error computing baseline or reform economy.",
                ),
            )
            log(
                api="compute",
                level="error",
                message=f"Error computing baseline or reform economy. Saved. {baseline_economy['status']} {reform_economy['status']}",
            )
        else:
            log(
                api="compute",
                level="info",
                message=f"Loading baseline and reform economies and computing reform impact.",
            )
            baseline_economy = json.loads(baseline_economy["economy_json"])
            reform_economy = json.loads(reform_economy["economy_json"])
            impact = compare_economic_outputs(baseline_economy, reform_economy)

            log(
                api="compute",
                level="info",
                message=f"Saving reform impact.",
            )

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

            log(
                api="compute",
                level="info",
                message=f"Reform impact saved.",
            )
    except Exception as e:
        log(
            api="compute",
            level="error",
            message=str(e),
        )
        try:
            error_obj = json.dumps({"error": str(e)})
        except Exception:
            error_obj = json.dumps({"error": "Unknown error."})
        options_hash = hash_object(json.dumps(options))
        database.set_in_table(
            "reform_impact",
            dict(
                **economy_kwargs,
                baseline_policy_id=baseline_policy_id,
                reform_policy_id=policy_id,
            ),
            dict(
                reform_impact_json=error_obj,
                start_time=datetime.strftime(
                    datetime.now(), "%Y-%m-%d %H:%M:%S.%f"
                ),
                options_json=json.dumps(options),
                options_hash=options_hash,
                status="error",
                message="Error computing baseline or reform economy, or in comparing them.",
            ),
        )


@app.route("/liveness_check", methods=[GET])
def liveness_check():
    return flask.Response(
        "OK", status=200, headers={"Content-Type": "text/plain"}
    )


@app.route("/readiness_check", methods=[GET])
def readiness_check():
    return flask.Response(
        "OK", status=200, headers={"Content-Type": "text/plain"}
    )
