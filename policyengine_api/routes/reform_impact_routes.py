from flask import Blueprint, request

from policyengine_api.data.v1_models import ReformImpact
from policyengine_api.services.reform_impacts_service import ReformImpactsService


reform_impact_bp = Blueprint("reform_impact", __name__)
reform_impacts_service = ReformImpactsService()

_MAX_SIMULATION_RESULTS = 1000
_DEFAULT_SIMULATION_RESULTS = 100


def _parse_result_limit(value: str | None) -> int:
    if value is None:
        return _DEFAULT_SIMULATION_RESULTS
    try:
        result_limit = int(value)
    except (TypeError, ValueError):
        return _DEFAULT_SIMULATION_RESULTS
    return max(1, min(result_limit, _MAX_SIMULATION_RESULTS))


@reform_impact_bp.route("/simulations", methods=["GET"])
def get_simulations() -> dict:
    """Return recent reform impacts, bounded to protect the database query."""
    result_limit = _parse_result_limit(request.args.get("max_results"))
    impacts = reform_impacts_service.get_recent_reform_impacts(result_limit)

    return {
        "result": [
            {
                column.name: getattr(impact, column.name)
                for column in ReformImpact.__table__.columns
            }
            for impact in impacts
        ]
    }
