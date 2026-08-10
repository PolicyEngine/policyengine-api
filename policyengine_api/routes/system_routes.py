from flask import Blueprint, Response, jsonify

from policyengine_api.readiness import is_ready
from policyengine_api.specification import OPENAPI_SPECIFICATION


system_bp = Blueprint("system", __name__)


@system_bp.route("/liveness-check", methods=["GET"])
def liveness_check() -> Response:
    return Response("OK", status=200, headers={"Content-Type": "text/plain"})


@system_bp.route("/readiness-check", methods=["GET"])
def readiness_check() -> Response:
    # The service is not ready until startup warmup compiles the simulation
    # machinery. Liveness remains unconditional so the worker is not restarted.
    if not is_ready():
        return Response(
            "NOT READY",
            status=503,
            headers={"Content-Type": "text/plain"},
        )
    return Response("OK", status=200, headers={"Content-Type": "text/plain"})


@system_bp.route("/specification", methods=["GET"])
def get_specification() -> Response:
    return jsonify(OPENAPI_SPECIFICATION)
