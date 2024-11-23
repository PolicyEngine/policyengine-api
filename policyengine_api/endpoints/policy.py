from policyengine_api.helpers import validate_country
from policyengine_api.data import database
from policyengine_api.utils import hash_object
from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
import json
from flask import Response, request


@validate_country
def get_policy(country_id: str, policy_id: int) -> dict:
    """
    Get policy data for a given country and policy ID.

    Args:
        country_id (str): The country ID.
        policy_id (int): The policy ID.

    Returns:
        dict: The policy record.
    """

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


@validate_country
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


@validate_country
def get_policy_search(country_id: str) -> dict:
    """
    Search for policies for a specified country

    Args:
        country_id (str): The country ID.

    Query Parameters:
        query (str): Optional search term to filter policies
        unique_only (bool): If true, return only unique policy-label combinations

    Returns:
        Response: Json response with:
            - On success: list of policies with id and label
            - On failure: error message and appropriate status code

    Example:
        GET /api/policies/us?query=tax&unique_only=true
    """

    query = request.args.get("query", "")
    # The "json.loads" default type is added to convert lowercase
    # "true" and "false" to Python-friendly bool values
    unique_only = request.args.get(
        "unique_only", default=False, type=json.loads
    )

    try:
        results = database.query(
            "SELECT id, label, policy_hash FROM policy WHERE country_id = ? AND label LIKE ?",
            (country_id, f"%{query}%"),
        )

        results = results.fetchall()

        if not results:
            body = dict(
                status="error",
                message=f"No policies found for country {country_id} for query '{query}",
            )
            return Response(
                json.dumps(body), status=404, mimetype="application/json"
            )

        # If unique_only is true, filter results to only include
        # items where everything except ID is unique
        if unique_only:
            processed_vals = set()
            new_results = []

            # Compare every label and hash to what's contained in processed_vals
            # If a label-hash set aren't already in processed_vals,
            # add them to new_results
            for policy in results:
                comparison_vals = policy["label"], policy["policy_hash"]
                if comparison_vals not in processed_vals:
                    new_results.append(policy)
                    processed_vals.add(comparison_vals)

            # Overwrite results with new_results
            results = new_results

        # Format into: [{ id: 1, label: "My policy" }, ...]
        policies = [
            dict(id=result["id"], label=result["label"]) for result in results
        ]
        body = dict(
            status="ok",
            message="Policies found",
            result=policies,
        )
        return Response(
            json.dumps(body), status=200, mimetype="application/json"
        )
    except Exception as e:
        body = dict(status="error", message=f"Internal server error: {e}")
        return Response(
            json.dumps(body), status=500, mimetype="application/json"
        )


@validate_country
def set_user_policy(country_id: str) -> dict:
    """
    Adds a record (if unique, barring type) to the user_policy table
    that defines a particular policy as saved by a user to "their
    policies"; this table also contains an optional "type" column that
    is currently unused
    """

    payload = request.json
    reform_label = payload.pop("reform_label", None)
    reform_id = payload.pop("reform_id")
    baseline_label = payload.pop("baseline_label", None)
    baseline_id = payload.pop("baseline_id")
    user_id = payload.pop("user_id")
    year = payload.pop("year")
    geography = payload.pop("geography")
    number_of_provisions = payload.pop("number_of_provisions")
    api_version = payload.pop("api_version")
    added_date = payload.pop("added_date")
    updated_date = payload.pop("updated_date")
    budgetary_impact = payload.pop("budgetary_impact", None)
    type = payload.pop("type", None)

    # The following code is a workaround to the fact that
    # SQLite's cursor method does not properly convert
    # 'WHERE x = None' to 'WHERE x IS NULL'; though SQLite
    # supports searching and setting with 'WHERE x IS y',
    # the production MySQL does not, requiring this

    # This workaround should be removed if and when a proper
    # ORM package is added to the API, and this package's
    # sanitization methods should be utilized instead
    nullable_keys = []
    not_null_values = []
    possible_nulls = {
        "reform_label": reform_label,
        "baseline_label": baseline_label,
    }

    for key, value in possible_nulls.items():
        if not value:
            nullable_keys.append(f"{key} IS NULL")
        else:
            nullable_keys.append(f"{key} = ?")
            not_null_values.append(value)

    nullable_key_string = " AND ".join(nullable_keys)

    # When setting a user policy, "unique" records contain
    # a unique set of the following pieces of data:
    # country_id, reform_id, baseline_id, user_id, year,
    # geography, reform_label, baseline_label;
    # added_date, budgetary_impact, updated_date,
    # number_of_provisions, and api_version are
    # all are changeable, and thus do not need
    # to be tested; type is not yet implemented

    try:
        row = database.query(
            f"SELECT * FROM user_policies WHERE country_id = ? AND reform_id = ? AND baseline_id = ? AND user_id = ? AND year = ? AND geography = ? AND {nullable_key_string}",
            (
                country_id,
                reform_id,
                baseline_id,
                user_id,
                year,
                geography,
                *not_null_values,
            ),
        ).fetchone()
        if row is not None:
            readable_row = dict(row)

            response = dict(
                status="ok",
                message=f"The reform #{reform_id} / baseline #{baseline_id} pair already exists for user {user_id}",
                result=dict(id=readable_row["id"]),
            )
            return Response(
                json.dumps(response),
                status=200,
                mimetype="application/json",
            )
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

    try:
        # Unfortunately, it's not possible to use RETURNING
        # with SQLite3 without rewriting the PolicyEngineDatabase
        # object or implementing a true ORM, thus the double query
        database.query(
            f"INSERT INTO user_policies (country_id, reform_label, reform_id, baseline_label, baseline_id, user_id, year, geography, number_of_provisions, api_version, added_date, updated_date, budgetary_impact, type) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                country_id,
                reform_label,
                reform_id,
                baseline_label,
                baseline_id,
                user_id,
                year,
                geography,
                number_of_provisions,
                api_version,
                added_date,
                updated_date,
                budgetary_impact,
                type,
            ),
        )

        row = database.query(
            f"SELECT * FROM user_policies WHERE country_id = ? AND reform_id = ? AND baseline_id = ? AND user_id = ? AND year = ? AND geography = ?",
            (country_id, reform_id, baseline_id, user_id, year, geography),
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

    response_body = dict(
        status="ok",
        message="Record created successfully",
        result=dict(
            id=row["id"],
            country_id=row["country_id"],
            reform_id=row["reform_id"],
            reform_label=row["reform_label"],
            baseline_id=row["baseline_id"],
            baseline_label=row["baseline_label"],
            user_id=row["user_id"],
            year=row["year"],
            geography=row["geography"],
            number_of_provisions=row["number_of_provisions"],
            api_version=row["api_version"],
            added_date=row["added_date"],
            updated_date=row["updated_date"],
            budgetary_impact=row["budgetary_impact"],
            type=row["type"],
        ),
    )

    return Response(
        json.dumps(response_body),
        status=201,
        mimetype="application/json",
    )


@validate_country
def get_user_policy(country_id: str, user_id: str) -> dict:
    """
    Fetch all saved user policies by user id
    """

    # Get the policy record for a given policy ID.
    rows = database.query(
        f"SELECT * FROM user_policies WHERE country_id = ? AND user_id = ?",
        (country_id, user_id),
    ).fetchall()

    rows_parsed = [
        dict(
            id=row["id"],
            country_id=row["country_id"],
            reform_id=row["reform_id"],
            reform_label=row["reform_label"],
            baseline_id=row["baseline_id"],
            baseline_label=row["baseline_label"],
            user_id=row["user_id"],
            year=row["year"],
            geography=row["geography"],
            number_of_provisions=row["number_of_provisions"],
            api_version=row["api_version"],
            added_date=row["added_date"],
            updated_date=row["updated_date"],
            budgetary_impact=row["budgetary_impact"],
            type=row["type"],
        )
        for row in rows
    ]

    if rows_parsed is None:
        response = dict(
            status="ok",
            message=f"No saved policies found for user {user_id}",
        )
        return Response(
            json.dumps(response),
            status=200,
            mimetype="application/json",
        )
    return dict(
        status="ok",
        message=None,
        result=rows_parsed,
    )


@validate_country
def update_user_policy(country_id: str) -> dict:
    """
    Update any parts of a user_policy, given a user_policy ID
    """

    # Construct the relevant UPDATE request
    setter_array = []
    args = []
    payload = request.json
    user_policy_id = payload.pop("id")

    for key in payload:
        setter_array.append(f"{key} = ?")
        args.append(payload[key])
    setter_phrase = ", ".join(setter_array)

    args.append(user_policy_id)
    sql_request = f"UPDATE user_policies SET {setter_phrase} WHERE id = ?"

    try:
        database.query(sql_request, (tuple(args)))
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
        status="ok",
        message="Record updated successfully",
        result=dict(id=user_policy_id),
    )

    return Response(
        json.dumps(response_body),
        status=200,
        mimetype="application/json",
    )
