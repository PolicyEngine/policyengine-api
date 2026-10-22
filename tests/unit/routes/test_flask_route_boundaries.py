from pathlib import Path

from flask import Flask

from policyengine_api.routes.economy_routes import economy_bp
from policyengine_api.routes.error_routes import error_bp
from policyengine_api.routes.household_routes import household_bp
from policyengine_api.routes.metadata_routes import metadata_bp
from policyengine_api.routes.policy_routes import policy_bp
from policyengine_api.routes.report_output_routes import report_output_bp
from policyengine_api.routes.simulation_routes import simulation_bp
from policyengine_api.routes.system_routes import system_bp

PACKAGE_ROOT = Path(__file__).parents[3] / "policyengine_api"
REGISTERED_BLUEPRINTS = (
    error_bp,
    metadata_bp,
    household_bp,
    policy_bp,
    economy_bp,
    simulation_bp,
    report_output_bp,
    system_bp,
)
# Routes that only legacy.policyengine.org or the API documentation used.
REMOVED_LEGACY_ROUTES = {
    ("/", "GET"),
    ("/specification", "GET"),
    ("/<country_id>/policies", "GET"),
    ("/<country_id>/user-policy", "POST"),
    ("/<country_id>/user-policy", "PUT"),
    ("/<country_id>/user-policy/<user_id>", "GET"),
    ("/<country_id>/user-profile", "POST"),
    ("/<country_id>/user-profile", "PUT"),
    ("/<country_id>/user-profile", "GET"),
    ("/simulations", "GET"),
}
REMOVED_BLUEPRINT_MODULES = (
    "home_routes",
    "reform_impact_routes",
    "user_profile_routes",
)


def _flask_rules() -> set[tuple[str, str]]:
    app = Flask(__name__)
    for blueprint in REGISTERED_BLUEPRINTS:
        app.register_blueprint(blueprint)
    return {
        (rule.rule, method)
        for rule in app.url_map.iter_rules()
        for method in rule.methods
        if method not in {"HEAD", "OPTIONS"}
    }


def test_legacy_flask_urls_are_owned_by_blueprints():
    rules = _flask_rules()

    assert {
        ("/<country_id>/policy", "POST"),
        ("/<country_id>/policy/<int:policy_id>", "GET"),
        ("/<country_id>/household/<household_id>/policy/<policy_id>", "GET"),
        ("/<country_id>/calculate", "POST"),
        ("/<country_id>/calculate-full", "POST"),
    } <= rules
    # Routes that only legacy.policyengine.org or the documentation used.
    assert rules & REMOVED_LEGACY_ROUTES == set()
    for module_name in REMOVED_BLUEPRINT_MODULES:
        assert not (PACKAGE_ROOT / "routes" / f"{module_name}.py").exists()


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
    for module_name in REMOVED_BLUEPRINT_MODULES:
        assert module_name not in source
    for blueprint in REGISTERED_BLUEPRINTS:
        assert f"app.register_blueprint({blueprint.name}_bp)" in source


def test_legacy_endpoints_package_is_removed():
    assert not any((PACKAGE_ROOT / "endpoints").rglob("*.py"))


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
