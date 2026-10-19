"""Flask routes for v1 policies, optionally mirrored to v2."""

import json

from flask import Blueprint, Response, request
from werkzeug.exceptions import BadRequest, NotFound

from policyengine_api.data.v1_models import Policy
from policyengine_api.data.v2.catalog.catalog_selection import (
    SUPPORTED_V2_COUNTRY_IDS,
)
from policyengine_api.migration_flags import (
    get_v1_policy_read_source,
    get_v1_policy_write_source,
)
from policyengine_api.response_factory import _make_error_response
from policyengine_api.services.policy_mirroring import (
    PolicyMirrorUnavailableError,
    mirror_policy_after_commit,
)
from policyengine_api.services.policy_service import PolicyService
from policyengine_api.utils.payload_validators import (
    validate_country,
    validate_set_policy_payload,
)

policy_bp = Blueprint("policy", __name__)
policy_service = PolicyService()


def _should_mirror_to_v2(country_id: str, write_source: str) -> bool:
    """Select immediate mirroring only for countries supported by API v2."""
    return write_source == "dual_write" and country_id in SUPPORTED_V2_COUNTRY_IDS


def _policy_configuration_unavailable() -> Response:
    return _make_error_response(
        "Policy persistence configuration is unavailable.",
        503,
    )


def _policy_mirror_unavailable() -> Response:
    return _make_error_response(
        "V2 policy mirroring is unavailable; retry the same request.",
        503,
    )


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
    """Return one stored v1 policy.

    Args:
        country_id (str): Country whose policies are searched.
        policy_id (int | str): ID of the stored policy; cast to int.

    Returns:
        Response: The policy as JSON under ``result``. An unknown ID gives 404,
        and an invalid policy read-source setting gives 503.

    """
    try:
        get_v1_policy_read_source()
    except ValueError:
        return _policy_configuration_unavailable()

    # Specifically cast policy_id to an integer
    policy_id = int(policy_id)

    policy = policy_service.get_policy(country_id, policy_id)
    result = None if policy is None else _serialize_policy(policy)

    if result is None:
        msg = f"Policy #{policy_id} not found."
        raise NotFound(msg)

    return Response(
        json.dumps({"status": "ok", "message": None, "result": result}),
        status=200,
    )


@policy_bp.route("/<country_id>/policy", methods=["POST"])
@validate_country
def set_policy(country_id: str) -> Response:
    """Store a policy, or return the ID of an identical one already stored.

    A policy is identical when its country, content hash and label all match;
    that case returns 200, a new policy returns 201. An invalid payload gives
    400, and an unavailable write configuration or v2 mirror gives 503.

    Args:
        country_id (str): Country to store the policy under.

    """
    payload = request.json

    is_payload_valid, message = validate_set_policy_payload(payload)
    if not is_payload_valid:
        msg = f"Invalid JSON data; details: {message}"
        raise BadRequest(msg)

    try:
        write_source = get_v1_policy_write_source()
    except ValueError:
        return _policy_configuration_unavailable()

    label = payload.pop("label", None)
    policy_json = payload.pop("data", None)
    mirror_to_v2 = _should_mirror_to_v2(country_id, write_source)

    creation = policy_service.set_policy(
        country_id,
        label,
        policy_json,
        prepare_for_mirroring=mirror_to_v2,
    )
    policy_id, message, is_existing_policy = creation

    if mirror_to_v2:
        snapshot = getattr(creation, "snapshot", None)
        if snapshot is None:
            return _policy_mirror_unavailable()
        try:
            mirror_policy_after_commit(snapshot)
        except PolicyMirrorUnavailableError:
            return _policy_mirror_unavailable()

    response_body = dict(
        status="ok",
        message=message,
        result=dict(
            policy_id=policy_id,
        ),
    )

    code = 200 if is_existing_policy else 201
    return Response(json.dumps(response_body), status=code, mimetype="application/json")
