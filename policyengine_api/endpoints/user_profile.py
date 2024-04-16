from flask import Response, request
from policyengine_api.country import validate_country
from policyengine_api.data import database
from datetime import datetime
import json


def set_user_profile(country_id: str) -> dict:
    """
    Creates a new user_profile
    """
    country_not_found = validate_country(country_id)
    if country_not_found:
        return country_not_found

    payload = request.json
    primary_country = country_id
    auth0_id = payload.pop("auth0_id")
    username = payload.pop("username", None)
    user_since = payload.pop("user_since")

    try:
        row = database.query(
            f"SELECT * FROM user_profiles WHERE auth0_id = ?",
            (auth0_id,),
        ).fetchone()
        if row is not None:
            response = dict(
                status="error",
                message=f"User with auth0_id {auth0_id} already exists",
            )
            return Response(
                json.dumps(response),
                status=403,
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
            f"INSERT INTO user_profiles (primary_country, auth0_id, username, user_since) VALUES (?, ?, ?, ?)",
            (primary_country, auth0_id, username, user_since),
        )

        row = database.query(
            f"SELECT * FROM user_profiles WHERE auth0_id = ?", (auth0_id,)
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
        result=dict(user_id=row["user_id"]),
    )

    return Response(
        json.dumps(response_body),
        status=201,
        mimetype="application/json",
    )


def get_user_profile(country_id: str) -> dict:
    """
    Get a user profile in one of two ways: by auth0_id,
    which returns all data, and by user_id, which returns
    all data except auth0_id
    """

    DATETIME_TYPE_KEYS = [
        "user_since"
    ]

    country_not_found = validate_country(country_id)
    if country_not_found:
        return country_not_found

    if len(request.args) != 1:
        return Response(
            json.dumps(
                {
                    "message": f"Improperly formed request: {len(request.args)} args passed, when 1 is required"
                }
            ),
            status=500,
            mimetype="application/json",
        )

    label = ""
    value = None
    if request.args.get("auth0_id"):
        label = "auth0_id"
        value = request.args.get("auth0_id")
    elif request.args.get("user_id"):
        label = "user_id"
        value = request.args.get("user_id")
    else:
        return Response(
            json.dumps(
                {
                    "message": "Improperly formed request: auth0_id or user_id must be provided"
                }
            ),
            status=500,
            mimetype="application/json",
        )

    try:
        row = database.query(
            f"SELECT * FROM user_profiles WHERE {label} = ?", (value,)
        ).fetchone()

        readable_row = dict(row)
        for key in DATETIME_TYPE_KEYS:
            readable_row[key] = datetime.strftime(readable_row[key], "%Y-%m-%d %H:%M:%S")
        if label == "user_id":
            del readable_row["auth0_id"]

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
        message=f"User #{readable_row['user_id']} found successfully",
        result=readable_row,
    )

    return Response(
        json.dumps(response_body),
        status=200,
        mimetype="application/json",
    )


def update_user_profile(country_id: str) -> dict:
    """
    Update any part of a user_profile, given a user_id,
    except the auth0_id value; any attempt to edit this
    will assume malicious intent and 403
    """

    country_not_found = validate_country(country_id)
    if country_not_found:
        return country_not_found

    # Construct the relevant UPDATE request
    setter_array = []
    args = []
    payload = request.json

    # This must be popped before all others to ensure
    # it is not added as an item to modify
    user_id = payload.pop("user_id")

    for key in payload:
        if key == "auth0_id":
            return Response(
                json.dumps(
                    {
                        "message": "Unauthorized attempt to modify auth0_id parameter; request denied"
                    }
                ),
                status=403,
                mimetype="application/json",
            )
        setter_array.append(f"{key} = ?")
        args.append(payload[key])
    setter_phrase = ", ".join(setter_array)

    args.append(user_id)
    sql_request = f"UPDATE user_profiles SET {setter_phrase} WHERE user_id = ?"

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
        message=f"User profile #{user_id} updated successfully",
        result=dict(user_id=user_id),
    )

    return Response(
        json.dumps(response_body),
        status=200,
        mimetype="application/json",
    )
