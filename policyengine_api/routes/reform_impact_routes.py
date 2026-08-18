from datetime import datetime
import json
from typing import Any

from flask import Blueprint, Response, request

from policyengine_api.runtime_cache.repositories import CachedReformImpact
from policyengine_api.services.reform_impacts_service import ReformImpactsService


reform_impact_bp = Blueprint("reform_impact", __name__)
reform_impacts_service = ReformImpactsService()

_MAX_SIMULATION_RESULTS = 1000
_DEFAULT_SIMULATION_RESULTS = 100


def _serialize_v1_json(value: dict[str, Any] | None) -> str | None:
    return None if value is None else json.dumps(value)


def _serialize_v1_datetime(value: datetime | None) -> str | None:
    return None if value is None else str(value)


def _serialize_v1_reform_impact(impact: CachedReformImpact) -> dict[str, object]:
    """Project a cached impact onto the explicit historical v1 response shape."""

    return {
        "reform_impact_id": impact.reform_impact_id,
        "baseline_policy_id": impact.baseline_policy_id,
        "reform_policy_id": impact.reform_policy_id,
        "country_id": impact.country_id,
        "region": impact.region,
        "dataset": impact.dataset,
        "time_period": impact.time_period,
        "options_json": _serialize_v1_json(impact.options_json),
        "options_hash": impact.options_hash,
        "api_version": impact.api_version,
        "reform_impact_json": _serialize_v1_json(impact.reform_impact_json),
        "status": impact.status,
        "message": impact.message,
        "start_time": _serialize_v1_datetime(impact.start_time),
        "end_time": _serialize_v1_datetime(impact.end_time),
        "execution_id": impact.execution_id,
    }


def _parse_result_limit(value: str | None) -> int:
    if value is None:
        return _DEFAULT_SIMULATION_RESULTS
    try:
        result_limit = int(value)
    except (TypeError, ValueError):
        return _DEFAULT_SIMULATION_RESULTS
    return max(1, min(result_limit, _MAX_SIMULATION_RESULTS))


@reform_impact_bp.route("/simulations", methods=["GET"])
def get_simulations() -> Response:
    """Return recent reform impacts through a bounded cache-index lookup."""
    result_limit = _parse_result_limit(request.args.get("max_results"))
    impacts = reform_impacts_service.get_recent_reform_impacts(result_limit)

    return Response(
        json.dumps(
            {"result": [_serialize_v1_reform_impact(impact) for impact in impacts]}
        ),
        status=200,
        mimetype="application/json",
    )
