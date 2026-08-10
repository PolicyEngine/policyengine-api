import json

from flask import Blueprint, Response, request
from werkzeug.exceptions import BadRequest, NotFound

from policyengine_api.data.v1_models import Policy, UserPolicy
from policyengine_api.services.policy_service import PolicyService
from policyengine_api.services.user_policy_service import UserPolicyService
from policyengine_api.utils.payload_validators import (
    validate_country,
    validate_set_policy_payload,
)

policy_bp = Blueprint("policy", __name__)
policy_service = PolicyService()
user_policy_service = UserPolicyService()


def _serialize_policy(policy: Policy) -> dict:
    return {
        "id": policy.id,
        "country_id": policy.country_id,
        "label": policy.label,
        "api_version": policy.api_version,
        "policy_json": policy.policy_json,
        "policy_hash": policy.policy_hash,
    }


@policy_bp.route("/<country_id>/policy/<int:policy_id>", methods=["GET"])
@validate_country
def get_policy(country_id: str, policy_id: int | str) -> Response:
    """
    Get policy data for a given country and policy ID.

    Args:
        country_id (str)
        policy_id (int | str)

    Returns:
        Response: A Flask response object containing the
        policy data in JSON format
    """

    # Specifically cast policy_id to an integer
    policy_id = int(policy_id)

    policy = policy_service.get_policy(country_id, policy_id)
    result = None if policy is None else _serialize_policy(policy)

    if result is None:
        raise NotFound(f"Policy #{policy_id} not found.")

    return Response(
        json.dumps({"status": "ok", "message": None, "result": result}),
        status=200,
    )


@policy_bp.route("/<country_id>/policy", methods=["POST"])
@validate_country
def set_policy(country_id: str) -> Response:
    """
    Set policy data for given country and policy. If policy already exists,
    return existing policy and 200.

    Args:
        country_id (str)
    """

    payload = request.json

    is_payload_valid, message = validate_set_policy_payload(payload)
    if not is_payload_valid:
        raise BadRequest(f"Invalid JSON data; details: {message}")

    label = payload.pop("label", None)
    policy_json = payload.pop("data", None)

    policy_id, message, is_existing_policy = policy_service.set_policy(
        country_id,
        label,
        policy_json,
    )

    response_body = dict(
        status="ok",
        message=message,
        result=dict(
            policy_id=policy_id,
        ),
    )

    code = 200 if is_existing_policy else 201
    return Response(json.dumps(response_body), status=code, mimetype="application/json")


def _serialize_user_policy(user_policy: UserPolicy) -> dict:
    return {
        column.name: getattr(user_policy, column.name)
        for column in UserPolicy.__table__.columns
    }


@policy_bp.route("/<country_id>/policies", methods=["GET"])
@validate_country
def get_policy_search(country_id: str) -> Response:
    """Search policies for a country."""
    query = request.args.get("query", "")
    unique_only = request.args.get("unique_only", default=False, type=json.loads)

    try:
        results = policy_service.search_policies(
            country_id,
            query,
            unique_only=unique_only,
        )
        if not results:
            return Response(
                json.dumps(
                    dict(
                        status="error",
                        message=(
                            f"No policies found for country {country_id} for query "
                            f"'{query}"
                        ),
                    )
                ),
                status=404,
                mimetype="application/json",
            )

        policies = [dict(id=result.id, label=result.label) for result in results]
        return Response(
            json.dumps(
                dict(
                    status="ok",
                    message="Policies found",
                    result=policies,
                )
            ),
            status=200,
            mimetype="application/json",
        )
    except Exception as error:
        return Response(
            json.dumps(
                dict(
                    status="error",
                    message=f"Internal server error: {error}",
                )
            ),
            status=500,
            mimetype="application/json",
        )


@policy_bp.route("/<country_id>/user-policy", methods=["POST"])
@validate_country
def set_user_policy(country_id: str) -> Response:
    """Create a saved policy for a user, or return its existing ID."""
    payload = request.json
    reform_label = payload.pop("reform_label", None)
    reform_id = payload.pop("reform_id")
    baseline_label = payload.pop("baseline_label", None)
    baseline_id = payload.pop("baseline_id")
    user_id = payload.pop("user_id")
    year = payload.pop("year")
    geography = payload.pop("geography")
    dataset = payload.pop("dataset", None)
    number_of_provisions = payload.pop("number_of_provisions")
    api_version = payload.pop("api_version")
    added_date = payload.pop("added_date")
    updated_date = payload.pop("updated_date")
    budgetary_impact = payload.pop("budgetary_impact", None)
    policy_type = payload.pop("type", None)

    values = {
        "country_id": country_id,
        "reform_id": reform_id,
        "reform_label": reform_label,
        "baseline_id": baseline_id,
        "baseline_label": baseline_label,
        "user_id": user_id,
        "year": year,
        "geography": geography,
        "dataset": dataset,
        "number_of_provisions": number_of_provisions,
        "api_version": api_version,
        "added_date": added_date,
        "updated_date": updated_date,
        "budgetary_impact": budgetary_impact,
        "type": policy_type,
    }

    try:
        creation = user_policy_service.create_or_get_user_policy(values)
        user_policy = creation.user_policy
        if not creation.created:
            return Response(
                json.dumps(
                    dict(
                        status="ok",
                        message=(
                            f"The reform #{reform_id} / baseline #{baseline_id} pair "
                            f"already exists for user {user_id}"
                        ),
                        result=dict(id=user_policy.id),
                    )
                ),
                status=200,
                mimetype="application/json",
            )
    except Exception as error:
        return Response(
            json.dumps(
                {
                    "message": (
                        f"Internal database error: {error}; please try again later."
                    )
                }
            ),
            status=500,
            mimetype="application/json",
        )

    return Response(
        json.dumps(
            dict(
                status="ok",
                message="Record created successfully",
                result=_serialize_user_policy(user_policy),
            )
        ),
        status=201,
        mimetype="application/json",
    )


@policy_bp.route("/<country_id>/user-policy/<user_id>", methods=["GET"])
@validate_country
def get_user_policy(country_id: str, user_id: str) -> dict:
    """Fetch all saved policies for a user."""
    user_policies = user_policy_service.list_user_policies(country_id, user_id)
    return dict(
        status="ok",
        message=None,
        result=[_serialize_user_policy(row) for row in user_policies],
    )


UPDATE_USER_POLICY_ALLOWED_FIELDS = frozenset(
    {
        "reform_label",
        "baseline_label",
        "year",
        "geography",
        "dataset",
        "number_of_provisions",
        "api_version",
        "added_date",
        "updated_date",
        "budgetary_impact",
        "type",
    }
)


@policy_bp.route("/<country_id>/user-policy", methods=["PUT"])
@validate_country
def update_user_policy(country_id: str) -> Response:
    """Update mutable fields on a saved user policy."""
    payload = request.json
    if not isinstance(payload, dict) or "id" not in payload:
        return Response(
            json.dumps({"message": "Request body must include an 'id' field."}),
            status=400,
            mimetype="application/json",
        )

    user_policy_id = payload.pop("id")
    unknown_keys = [
        key for key in payload if key not in UPDATE_USER_POLICY_ALLOWED_FIELDS
    ]
    if unknown_keys:
        return Response(
            json.dumps(
                {
                    "message": (
                        "Request body contains unsupported fields: "
                        f"{sorted(unknown_keys)}"
                    )
                }
            ),
            status=400,
            mimetype="application/json",
        )

    if not payload:
        return Response(
            json.dumps(
                {"message": "Request body must include at least one field to update."}
            ),
            status=400,
            mimetype="application/json",
        )

    try:
        user_policy_service.update_user_policy(user_policy_id, payload)
    except Exception as error:
        return Response(
            json.dumps(
                {
                    "message": (
                        f"Internal database error: {error}; please try again later."
                    )
                }
            ),
            status=500,
            mimetype="application/json",
        )

    return Response(
        json.dumps(
            dict(
                status="ok",
                message="Record updated successfully",
                result=dict(id=user_policy_id),
            )
        ),
        status=200,
        mimetype="application/json",
    )
