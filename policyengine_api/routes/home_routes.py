from flask import Blueprint


home_bp = Blueprint("home", __name__)


@home_bp.route("/", methods=["GET"])
def get_home() -> str:
    """Get the home page of the PolicyEngine API."""
    return (
        "<h1>PolicyEngine households API</h1>"
        "<p>Use this API to compute the impact of public policy on individual "
        "households.</p>"
    )
