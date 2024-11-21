from flask import Blueprint

simulation_analysis_bp = Blueprint("simulation_analysis", __name__)
from policyengine_api.endpoints.simulation_analysis import execute_simulation_analysis

@simulation_analysis_bp.route("/", methods=["POST"])
def execute_simulation_analysis_placeholder(country_id):
    return execute_simulation_analysis(country_id)
