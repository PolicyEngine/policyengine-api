"""Regression tests for issue #3446.

The economy routes originally stacked @validate_country above @bp.route.
Because Flask only inspects the function registered by bp.route, the wrapping
logic ran in the wrong order. An invalid country must produce a 400 from
validate_country instead of a 200/500 from the view function.
"""

from flask import Flask

from policyengine_api.routes.economy_routes import economy_bp


def _client_with(*blueprints) -> object:
    app = Flask(__name__)
    app.config["TESTING"] = True
    for bp in blueprints:
        app.register_blueprint(bp)
    return app.test_client()


def test_economy_route_rejects_bogus_country():
    client = _client_with(economy_bp)
    response = client.get("/bogus/economy/1/over/2?region=us&time_period=2025")
    assert response.status_code == 400
