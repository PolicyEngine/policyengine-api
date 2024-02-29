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


def get_policy(country_id: str, policy_id: int) -> dict:
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
    Set policy data for a given country and policy. If the policy already exists,
    fail quietly by returning a 200, but passing a warning message and the previously
    created policy

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

    # Check if policy already exists.
    try:
        # The following code is a workaround to the fact that
        # SQLite's cursor method does not properly convert
        # 'WHERE x = None' to 'WHERE x IS NULL'; though SQLite
        # supports searching and setting with 'WHERE x IS y',
        # the production MySQL does not, requiring this

        # This workaround should be removed if and when a proper
        # ORM package is added to the API, and this package's
        # sanitization methods should be utilized instead
        label_value = "IS NULL" if not label else "= ?"
        args = [country_id, policy_hash]
        if label:
            args.append(label)

        row = database.query(
            f"SELECT * FROM policy WHERE country_id = ? AND policy_hash = ? AND label {label_value}",
            tuple(args),
        ).fetchone()
    except Exception as e:
        return Response(
            json.dumps(
                {
                    "message": f"Internal database error: {e}; please try again later."
                }
            ),
            status=500,
            mimetype="application/json",
        )

    code = None
    message = None
    status = None
    policy_id = None

    if row is not None:
        policy_id = str(row["id"])
        message = (
            "Warning: Record created previously with this label. To create "
            + "a new record, change the submitted data's country ID, policy "
            + "parameters, or label, and emit the request again"
        )
        status = "ok"
        code = 200

    else:
        message = None
        status = "ok"
        code = 201

        try:
            database.query(
                f"INSERT INTO policy (country_id, policy_json, policy_hash, label, api_version) VALUES (?, ?, ?, ?, ?)",
                (
                    country_id,
                    json.dumps(policy_json),
                    policy_hash,
                    label,
                    api_version,
                ),
            )

            # The following code is a workaround to the fact that
            # SQLite's cursor method does not properly convert
            # 'WHERE x = None' to 'WHERE x IS NULL'; though SQLite
            # supports searching and setting with 'WHERE x IS y',
            # the production MySQL does not, requiring this

            # This workaround should be removed if and when a proper
            # ORM package is added to the API, and this package's
            # sanitization methods should be utilized instead
            label_value = "IS NULL" if not label else "= ?"
            args = [country_id, policy_hash]
            if label:
                args.append(label)

            policy_id = database.query(
                f"SELECT id FROM policy WHERE country_id = ? AND policy_hash = ? AND label {label_value}",
                (tuple(args)),
            ).fetchone()["id"]

        except Exception as e:
            return Response(
                json.dumps(
                    {
                        "message": f"Internal database error: {e}; please try again later."
                    }
                ),
                status=500,
                mimetype="application/json",
            )

    response_body = dict(
        status=status,
        message=message,
        result=dict(
            policy_id=policy_id,
        ),
    )
    return Response(
        json.dumps(response_body),
        status=code,
        mimetype="application/json",
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
    # The "json.loads" default type is added to convert lowercase 
    # "true" and "false" to Python-friendly bool values
    unique_only = request.args.get("unique_only", default=False, type=json.loads)

    country_not_found = validate_country(country_id)
    if country_not_found:
        return country_not_found

    results = database.query(
        "SELECT id, label, policy_hash FROM policy WHERE country_id = ? AND label LIKE ?",
        (country_id, f"%{query}%"),
    )
    if results is None:
        return dict(
            status="error",
            message=f"Policy not found in {country_id}",
        )
    else:
        results = results.fetchall()

    # If unique_only is true, filter results to only include
    # items where everything except ID is unique
    if unique_only:
        processed_vals = set()
        new_results = []

        # Compare every label and hash to what's contained in processed_vals
        # If a label-hash set aren't already in processed_vals,
        # add them to new_results
        for policy in results[:]:
            comparison_vals = policy["label"],policy["policy_hash"]
            if comparison_vals not in processed_vals:
                new_results.append(policy)
                processed_vals.add(comparison_vals)
        
        # Overwrite results with new_results
        results = new_results

    # Format into: [{ id: 1, label: "My policy" }, ...]
    policies = [
        dict(id=result["id"], label=result["label"]) for result in results
    ]
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
