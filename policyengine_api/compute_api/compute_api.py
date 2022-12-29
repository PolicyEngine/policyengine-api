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
from policyengine_api.constants import GET, POST, VERSION
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
    policy_id = json_body.get("policy_id")
    baseline_policy_id = json_body.get("baseline_policy_id")
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
):
    options_hash = hash_object(json.dumps(options))
    economy = database.get_in_table(
        "economy",
        country_id=country_id,
        policy_id=policy_id,
        region=region,
        time_period=time_period,
        options_hash=options_hash,
        api_version=VERSION,
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
                    country_id=country_id,
                    policy_id=policy_id,
                    region=region,
                    time_period=time_period,
                    options_hash=options_hash,
                    api_version=VERSION,
                ),
                dict(
                    economy_json=json.dumps(economy_result),
                    options_json=json.dumps(options),
                    status="ok",
                    start_time=datetime.strftime(
                        datetime.now(), "%Y-%m-%d %H:%M:%S"
                    ),
                ),
            )
        except Exception as e:
            database.set_in_table(
                "economy",
                dict(
                    country_id=country_id,
                    policy_id=policy_id,
                    region=region,
                    time_period=time_period,
                    options_hash=options_hash,
                    api_version=VERSION,
                ),
                dict(
                    economy_json=json.dumps({}),
                    options_json=json.dumps(options),
                    status="error",
                    message=str(e),
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
    log(
        api="compute",
        level="info",
        message=f"Computing reform impact for policy {policy_id} and baseline policy {baseline_policy_id}.",
    )
    try:
        economy_arguments = region, time_period, options

        for required_policy_id in [baseline_policy_id, policy_id]:
            ensure_economy_computed(
                country_id,
                required_policy_id,
                *economy_arguments,
            )

        options_hash = hash_object(json.dumps(options))

        economy_kwargs = dict(
            country_id=country_id,
            region=region,
            time_period=time_period,
            options_json=json.dumps(options),
            options_hash=options_hash,
            api_version=VERSION,
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

            log(
                api="compute",
                level="error",
                message=f"Error computing baseline or reform economy. Saved.",
            )
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

            database.set_in_table(
                "reform_impact",
                dict(
                    **economy_kwargs,
                    baseline_policy_id=baseline_policy_id,
                    reform_policy_id=policy_id,
                ),
                dict(
                    reform_impact_json=json.dumps(impact),
                    status="ok",
                ),
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
                    datetime.now(), "%Y-%m-%d %H:%M:%S"
                ),
                status="error",
                message="Error computing baseline or reform economy, or in comparing them.",
            ),
        )
