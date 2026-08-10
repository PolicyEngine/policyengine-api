from datetime import datetime
import json

from flask import Blueprint, Response, request

from policyengine_api.data.v1_models import ReformImpact
from policyengine_api.services.reform_impacts_service import ReformImpactsService


reform_impact_bp = Blueprint("reform_impact", __name__)
reform_impacts_service = ReformImpactsService()

_MAX_SIMULATION_RESULTS = 1000
_DEFAULT_SIMULATION_RESULTS = 100


def _serialize_v1_reform_impact(impact: ReformImpact) -> dict:
    """Project canonical ORM values onto the historical v1 response shape."""

    result = {
        column.name: getattr(impact, column.name)
        for column in ReformImpact.__table__.columns
    }
    for field in ("options_json", "reform_impact_json"):
        value = result[field]
        if value is not None and not isinstance(value, str):
            result[field] = json.dumps(value)
    for field in ("start_time", "end_time"):
        value = result[field]
        if isinstance(value, datetime):
            result[field] = str(value)
    return result


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
    """Return recent reform impacts, bounded to protect the database query."""
    result_limit = _parse_result_limit(request.args.get("max_results"))
    impacts = reform_impacts_service.get_recent_reform_impacts(result_limit)

    return Response(
        json.dumps(
            {"result": [_serialize_v1_reform_impact(impact) for impact in impacts]}
        ),
        status=200,
        mimetype="application/json",
    )
