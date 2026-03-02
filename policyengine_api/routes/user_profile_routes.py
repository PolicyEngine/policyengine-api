from flask import Blueprint, Response, request
from policyengine_api.utils.payload_validators import validate_country
from policyengine_api.data import database
import json
from policyengine_api.services.user_service import UserService
from werkzeug.exceptions import BadRequest, NotFound
import time

user_profile_bp = Blueprint("user_profile", __name__)
user_service = UserService()


@user_profile_bp.route("/<country_id>/user-profile", methods=["POST"])
@validate_country
def set_user_profile(country_id: str) -> Response:
    """
    Creates a new user_profile
    """

    payload = request.json
    if payload is None:
        raise BadRequest("Payload missing from request")

    auth0_id = payload.pop("auth0_id")
    username = payload.pop("username", None)
    user_since = payload.pop("user_since")

    created, row = user_service.create_profile(
        primary_country=country_id,
        auth0_id=auth0_id,
        username=username,
        user_since=user_since,
    )

    response = dict(
        status="ok",
        message="Record created successfully" if created else "Record exists",
        result=dict(
            user_id=row["user_id"],
            primary_country=row["primary_country"],
            username=row["username"],
            user_since=row["user_since"],
        ),
    )
    return Response(
        json.dumps(response),
        status=201 if created else 200,
        mimetype="application/json",
    )


@user_profile_bp.route("/<country_id>/user-profile", methods=["GET"])
@validate_country
def get_user_profile(country_id: str) -> Response:
    auth0_id = request.args.get("auth0_id")
    user_id = request.args.get("user_id")

    if (auth0_id is None) and (user_id is None):
        raise BadRequest("auth0_id or user_id must be provided")

    row = (
        user_service.get_profile(user_id=user_id)
        if auth0_id is None
        else user_service.get_profile(auth0_id=auth0_id)
    )

    if row is None:
        _, row = user_service.create_profile(
            primary_country=country_id,
            auth0_id=auth0_id if auth0_id is not None else "",
            username=None,
            user_since=str(int(time.time())),
        )

    readable_row = dict(row)
    # Delete auth0_id value if querying from user_id, as that value
    # is a more private attribute than all others
    if auth0_id is None:
        del readable_row["auth0_id"]

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


@user_profile_bp.route("/<country_id>/user-profile", methods=["PUT"])
@validate_country
def update_user_profile(country_id: str) -> Response:
    """
    Update any part of a user_profile, given a user_id,
    except the auth0_id value; any attempt to edit this
    will assume malicious intent and 403
    """

    # Construct the relevant UPDATE request
    setter_array = []
    args = []
    payload = request.json

    if payload is None:
        raise BadRequest("No user data provided in request")

    # TODO: we should validate the payload
    # to ensure type safety https://github.com/PolicyEngine/policyengine-api/issues/2054
    user_id = payload.pop("user_id")
    username = payload.pop("username", None)
    primary_country = payload.pop("primary_country", None)
    user_since = payload.pop("user_since", None)

    if user_id is None:
        raise BadRequest("Payload must include user_id")

    updated = user_service.update_profile(
        user_id=user_id,
        primary_country=primary_country,
        username=username,
        user_since=user_since,
    )

    if not updated:
        raise NotFound("No such user id")

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
