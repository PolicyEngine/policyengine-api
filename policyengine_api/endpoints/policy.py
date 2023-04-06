from policyengine_api.country import COUNTRIES, validate_country
from policyengine_api.data import database
from policyengine_api.utils import hash_object
from policyengine_api.constants import VERSION, COUNTRY_PACKAGE_VERSIONS
from policyengine_core.reforms import Reform
from policyengine_core.parameters import ParameterNode, Parameter
from policyengine_core.periods import instant
import json
from flask import Response, request
import sqlalchemy.exc


def get_policy(
    country_id: str, policy_id: int
) -> dict:
    """
    Get policy data for a given country and policy ID.

    Args:
        country_id (str): The country ID.
        policy_id (int): The policy ID.

    Returns:
        dict: The policy record.
    """
    country_not_found = validate_country(country_id)
    if country_not_found:
        return country_not_found
    # Get the policy record for a given policy ID.
    row = database.query(
        f"SELECT * FROM policy WHERE country_id = ? AND id = ?",
        (country_id, policy_id),
    ).fetchone()
    if row is None:
        response = dict(
            status="error",
            message=f"Policy #{policy_id} not found.",
        )
        return Response(
            json.dumps(response),
            status=404,
            mimetype="application/json",
        )
    policy = dict(row)
    policy["policy_json"] = json.loads(policy["policy_json"])
    return dict(
        status="ok",
        message=None,
        result=policy,
    )


def set_policy(
    country_id: str,
) -> dict:
    """
    Set policy data for a given country and policy ID.

    Args:
        country_id (str): The country ID.
    """
    country_not_found = validate_country(country_id)
    if country_not_found:
        return country_not_found
    
    payload = request.json
    label = payload.pop("label", None)
    policy_json = payload.pop("data", None)
    policy_hash = hash_object(policy_json)
    api_version = COUNTRY_PACKAGE_VERSIONS.get(country_id)

    try:
        database.query(
            f"INSERT INTO policy (country_id, policy_json, policy_hash, label, api_version) VALUES (?, ?, ?, ?, ?)",
            (country_id, json.dumps(policy_json), policy_hash, label, api_version),
        )
    except sqlalchemy.exc.IntegrityError:
        pass

    policy_id = database.query(
        f"SELECT id FROM policy WHERE country_id = ? AND policy_hash = ?",
        (country_id, policy_hash),
    ).fetchone()["id"]

    return dict(
        status="ok",
        message=None,
        result=dict(
            policy_id=policy_id,
        ),
    )




def get_policy_search(country_id: str) -> list:
    """
    Search for policies.

    Args:
        country_id (str): The country ID.
        query (str): The search query.

    Returns:
        list: The search results.
    """
    query = request.args.get("query", "")

    country_not_found = validate_country(country_id)
    if country_not_found:
        return country_not_found

    results = database.query(
        "SELECT id, label FROM policy WHERE country_id = ? AND label LIKE ?",
        (country_id, f"%{query}%"),
    )
    if results is None:
        return dict(
            status="error",
            message=f"Policy not found in {country_id}",
        )
    else:
        results = results.fetchall()
    # Format into: [{ id: 1, label: "My policy" }, ...]
    policies = [dict(id=result[0], label=result[1]) for result in results]
    return dict(
        status="ok",
        message=None,
        result=policies,
    )


def get_current_law_policy_id(country_id: str) -> int:
    return {
        "uk": 1,
        "us": 2,
        "ca": 3,
        "ng": 4,
    }[country_id]
