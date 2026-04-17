"""Regression tests for issue #3446.

economy_routes and ai_prompt_routes originally stacked
@validate_country above @bp.route. Because Flask only inspects the
function registered by bp.route, the wrapping logic ran in the wrong
order: validate_country bypassed the Response it returned, or Flask
saw a decorator that hadn't been registered as a route handler.
The fix puts @bp.route as the outermost decorator.

An invalid country must now produce a 400 from validate_country
instead of a 200/500 from the view function.
"""

from flask import Flask

from policyengine_api.routes.ai_prompt_routes import ai_prompt_bp
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


def test_ai_prompt_route_rejects_bogus_country():
    client = _client_with(ai_prompt_bp)
    # Use a payload that passes validate_sim_analysis_payload so the only
    # remaining reason to 400 is the unknown country_id. With the pre-#3446
    # decorator order the view runs first and reaches the service, so this
    # request would not be rejected on country grounds.
    valid_payload = {
        "currency": "USD",
        "selected_version": "v1.0",
        "time_period": "2024",
        "impact": {"value": 100},
        "policy_label": "Test Policy",
        "policy": {"type": "tax", "rate": 0.1},
        "region": "NA",
        "relevant_parameters": ["param1", "param2"],
        "relevant_parameter_baseline_values": [1.0, 2.0],
    }
    response = client.post("/bogus/ai-prompts/some_prompt", json=valid_payload)
    assert response.status_code == 400
