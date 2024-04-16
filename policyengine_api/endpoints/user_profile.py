from flask import Response, request
from policyengine_api.country import validate_country
from policyengine_api.data import database
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
            (
                auth0_id,
            ),
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
            (
                primary_country,
                auth0_id,
                username,
                user_since
            ),
        )

        row = database.query(
            f"SELECT * FROM user_profiles WHERE auth0_id = ?",
            (
                auth0_id,
            )
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
            user_id=row["user_id"]
        )
    )

    return Response(
        json.dumps(response_body),
        status=201,
        mimetype="application/json",
    )