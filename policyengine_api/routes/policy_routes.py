import json
import time

from flask import Blueprint, Response, request
from werkzeug.exceptions import BadRequest, NotFound

from policyengine_api.data.v1_models import Policy, UserPolicy
from policyengine_api.gcp_logging import logger
from policyengine_api.migration_flags import (
    get_v1_policy_read_source,
    get_v1_policy_write_source,
)
from policyengine_api.request_context import current_request_id
from policyengine_api.response_factory import _make_error_response
from policyengine_api.services.policy_mirroring import (
    PolicyMirrorUnavailableError,
    mirror_policy_after_commit,
)
from policyengine_api.services.policy_service import PolicyService
from policyengine_api.services.user_policy_service import (
    USER_POLICY_MUTABLE_FIELDS,
    UserPolicyPersistenceError,
    UserPolicyService,
)
from policyengine_api.services.user_policy_mirroring import (
    UserPolicyMirrorUnavailableError,
    mirror_pending_user_policy_events_after_commit,
)
from policyengine_api.utils.payload_validators import (
    validate_country,
    validate_set_policy_payload,
)

policy_bp = Blueprint("policy", __name__)
policy_service = PolicyService()
user_policy_service = UserPolicyService()


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


def _user_policy_mirror_unavailable() -> Response:
    return _make_error_response(
        "V2 saved-policy mirroring is unavailable; retry the same request.",
        503,
        include_status=False,
    )


def _safe_legacy_user_policy_id(value: object) -> int | None:
    if (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= 2_147_483_647
    ):
        return value
    return None


def _user_policy_persistence_failure(
    error: UserPolicyPersistenceError,
    *,
    operation: str,
    country_id: str,
    configured_write_source: str,
    started_at: float,
    legacy_user_policy_id: object | None = None,
) -> Response:
    """Return and record a failure without serializing exception details."""

    status_code = 503 if error.retryable else 500
    try:
        logger.log_struct(
            {
                "message": "V1 saved-policy persistence failed",
                "metric_name": "v1_user_policy_persistence_failures",
                "metric_value": 1,
                "resource": "user_policy",
                "operation": operation,
                "database_source": "cloud_sql",
                "configured_write_source": configured_write_source,
                "country_id": country_id,
                "legacy_user_policy_id": _safe_legacy_user_policy_id(
                    legacy_user_policy_id
                ),
                "request_id": current_request_id(),
                "outcome": "error",
                "failure_category": error.category.value,
                "http_status": status_code,
                "duration_ms": round(
                    (time.perf_counter() - started_at) * 1000,
                    3,
                ),
            },
            severity="ERROR",
        )
    except Exception:
        # A logging failure must not replace the persistence response.
        pass

    message = (
        "Policy database is temporarily unavailable; please try again later."
        if status_code == 503
        else "Internal database error; please try again later."
    )
    return _make_error_response(
        message,
        status_code,
        include_status=False,
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
    """
    Get policy data for a given country and policy ID.

    Args:
        country_id (str)
        policy_id (int | str)

    Returns:
        Response: A Flask response object containing the
        policy data in JSON format
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

    try:
        write_source = get_v1_policy_write_source()
    except ValueError:
        return _policy_configuration_unavailable()

    label = payload.pop("label", None)
    policy_json = payload.pop("data", None)

    creation = policy_service.set_policy(
        country_id,
        label,
        policy_json,
    )
    policy_id, message, is_existing_policy = creation

    if write_source == "dual_write":
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


def _serialize_user_policy(user_policy: UserPolicy) -> dict:
    return {
        column.name: getattr(user_policy, column.name)
        for column in UserPolicy.__table__.columns
        if column.name != "mirror_revision"
    }


@policy_bp.route("/<country_id>/policies", methods=["GET"])
@validate_country
def get_policy_search(country_id: str) -> Response:
    """Search policies for a country."""
    query = request.args.get("query", "")
    unique_only = request.args.get("unique_only", default=False, type=json.loads)

    try:
        get_v1_policy_read_source()
    except ValueError:
        return _policy_configuration_unavailable()

    try:
        results = policy_service.search_policies(
            country_id,
            query,
            unique_only=unique_only,
        )
        if not results:
            return _make_error_response(
                f"No policies found for country {country_id} for query '{query}",
                404,
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
    except Exception:
        return _make_error_response(
            "Internal server error; please try again later.",
            500,
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
        write_source = get_v1_policy_write_source()
        if write_source == "dual_write":
            get_v1_policy_read_source()
    except ValueError:
        return _policy_configuration_unavailable()

    persistence_started_at = time.perf_counter()
    try:
        creation = user_policy_service.create_or_get_user_policy(
            values,
            record_mirror_event=write_source == "dual_write",
        )
        user_policy = creation.user_policy
    except UserPolicyPersistenceError as error:
        return _user_policy_persistence_failure(
            error,
            operation="create",
            country_id=country_id,
            configured_write_source=write_source,
            started_at=persistence_started_at,
        )

    if write_source == "dual_write":
        if creation.mirror_revision is None:
            return _user_policy_mirror_unavailable()
        try:
            mirror_pending_user_policy_events_after_commit(
                country_id,
                creation.user_policy.id,
                through_revision=creation.mirror_revision,
                event_service=user_policy_service,
                reform_snapshot_loader=policy_service.get_policy_snapshot,
            )
        except UserPolicyMirrorUnavailableError:
            return _user_policy_mirror_unavailable()
        except Exception:
            return _user_policy_mirror_unavailable()

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
def get_user_policy(country_id: str, user_id: str) -> dict | Response:
    """Fetch all saved policies for a user."""
    try:
        get_v1_policy_read_source()
    except ValueError:
        return _policy_configuration_unavailable()
    user_policies = user_policy_service.list_user_policies(country_id, user_id)
    return dict(
        status="ok",
        message=None,
        result=[_serialize_user_policy(row) for row in user_policies],
    )


UPDATE_USER_POLICY_ALLOWED_FIELDS = USER_POLICY_MUTABLE_FIELDS


@policy_bp.route("/<country_id>/user-policy", methods=["PUT"])
@validate_country
def update_user_policy(country_id: str) -> Response:
    """Update mutable fields on a saved user policy."""
    payload = request.json
    if not isinstance(payload, dict) or "id" not in payload:
        return _make_error_response(
            "Request body must include an 'id' field.",
            400,
            include_status=False,
        )

    user_policy_id = payload.pop("id")
    unknown_keys = [
        key for key in payload if key not in UPDATE_USER_POLICY_ALLOWED_FIELDS
    ]
    if unknown_keys:
        return _make_error_response(
            f"Request body contains unsupported fields: {sorted(unknown_keys)}",
            400,
            include_status=False,
        )

    if not payload:
        return _make_error_response(
            "Request body must include at least one field to update.",
            400,
            include_status=False,
        )

    try:
        write_source = get_v1_policy_write_source()
        if write_source == "dual_write":
            get_v1_policy_read_source()
    except ValueError:
        return _policy_configuration_unavailable()

    persistence_started_at = time.perf_counter()
    try:
        update = user_policy_service.update_user_policy(
            country_id,
            user_policy_id,
            payload,
            record_mirror_event=write_source == "dual_write",
        )
    except UserPolicyPersistenceError as error:
        return _user_policy_persistence_failure(
            error,
            operation="update",
            country_id=country_id,
            configured_write_source=write_source,
            started_at=persistence_started_at,
            legacy_user_policy_id=user_policy_id,
        )

    if update is None:
        return _make_error_response(
            f"User policy #{user_policy_id} not found.",
            404,
            include_status=False,
        )

    if write_source == "dual_write":
        if update.mirror_revision is None:
            return _user_policy_mirror_unavailable()
        try:
            mirror_pending_user_policy_events_after_commit(
                country_id,
                update.user_policy.id,
                through_revision=update.mirror_revision,
                event_service=user_policy_service,
                reform_snapshot_loader=policy_service.get_policy_snapshot,
            )
        except UserPolicyMirrorUnavailableError:
            return _user_policy_mirror_unavailable()
        except Exception:
            return _user_policy_mirror_unavailable()

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
