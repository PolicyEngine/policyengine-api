from pathlib import Path

from flask import Flask

from policyengine_api.routes.home_routes import home_bp
from policyengine_api.routes.household_routes import household_bp
from policyengine_api.routes.policy_routes import policy_bp
from policyengine_api.routes.reform_impact_routes import reform_impact_bp
from policyengine_api.routes.system_routes import system_bp


PACKAGE_ROOT = Path(__file__).parents[3] / "policyengine_api"


def test_legacy_flask_urls_are_owned_by_blueprints():
    app = Flask(__name__)
    app.register_blueprint(home_bp)
    app.register_blueprint(household_bp)
    app.register_blueprint(policy_bp)
    app.register_blueprint(reform_impact_bp)
    app.register_blueprint(system_bp)

    rules = {
        (rule.rule, method)
        for rule in app.url_map.iter_rules()
        for method in rule.methods
        if method not in {"HEAD", "OPTIONS"}
    }

    assert {
        ("/", "GET"),
        ("/<country_id>/policies", "GET"),
        ("/<country_id>/household/<household_id>/policy/<policy_id>", "GET"),
        ("/<country_id>/calculate", "POST"),
        ("/<country_id>/calculate-full", "POST"),
        ("/<country_id>/user-policy", "POST"),
        ("/<country_id>/user-policy", "PUT"),
        ("/<country_id>/user-policy/<user_id>", "GET"),
        ("/simulations", "GET"),
        ("/liveness-check", "GET"),
        ("/readiness-check", "GET"),
        ("/specification", "GET"),
    } <= rules


def test_flask_app_assembles_blueprints_without_legacy_endpoint_wiring():
    source = (PACKAGE_ROOT / "api.py").read_text(encoding="utf-8")

    assert "policyengine_api.endpoints" not in source
    assert "from .endpoints" not in source
    assert "Legacy endpoints" not in source
    assert "get_policy_search" not in source
    assert "get_household_under_policy" not in source
    assert "get_calculate" not in source
    assert "set_user_policy" not in source
    assert "get_user_policy" not in source
    assert "update_user_policy" not in source
    assert "get_simulations" not in source
    assert "@app.route" not in source
    assert "app.route(" not in source


def test_legacy_endpoints_package_is_removed():
    assert not any((PACKAGE_ROOT / "endpoints").rglob("*.py"))


def test_economy_comparison_logic_is_not_in_the_http_layer():
    comparison_module = PACKAGE_ROOT / "services/economy_comparison.py"

    assert comparison_module.exists()
    source = comparison_module.read_text(encoding="utf-8")
    assert "from flask" not in source
    assert "import flask" not in source


def test_calculation_route_delegates_domain_processing_to_its_service():
    source = (PACKAGE_ROOT / "routes/household_routes.py").read_text(encoding="utf-8")

    assert "country.calculate(" not in source
    assert "find_unrecognized_inputs(" not in source
    assert "drop_deprecated_inputs(" not in source


def test_routes_do_not_construct_json_error_responses_inline():
    offenders = []
    for path in sorted((PACKAGE_ROOT / "routes").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        if '"status": "error"' in source or 'status="error"' in source:
            offenders.append(path.name)

    assert offenders == []
