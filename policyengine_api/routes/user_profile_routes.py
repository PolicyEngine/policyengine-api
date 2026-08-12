from flask import Blueprint, Response, request
from policyengine_api.data.v1_models import UserProfile
from policyengine_api.utils.payload_validators import validate_country
import json
from policyengine_api.services.user_service import UserService
from werkzeug.exceptions import BadRequest, NotFound

user_profile_bp = Blueprint("user_profile", __name__)
user_service = UserService()


def _serialize_user_profile(
    profile: UserProfile,
    *,
    include_auth0_id: bool,
) -> dict:
    result = {
        "user_id": profile.user_id,
        "primary_country": profile.primary_country,
        "username": profile.username,
        "user_since": profile.user_since,
    }
    if include_auth0_id:
        result["auth0_id"] = profile.auth0_id
    return result


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

    created, profile = user_service.create_profile(
        primary_country=country_id,
        auth0_id=auth0_id,
        username=username,
        user_since=user_since,
    )
    result = _serialize_user_profile(profile, include_auth0_id=False)

    response = dict(
        status="ok",
        message="Record created successfully" if created else "Record exists",
        result=result,
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

    profile = (
        user_service.get_profile(user_id=user_id)
        if auth0_id is None
        else user_service.get_profile(auth0_id=auth0_id)
    )
    readable_row = (
        None
        if profile is None
        else _serialize_user_profile(
            profile,
            include_auth0_id=auth0_id is not None,
        )
    )

    if readable_row is None:
        raise NotFound("No such user")

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
