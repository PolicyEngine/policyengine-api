from policyengine_api.data import local_database

"""

CREATE TABLE IF NOT EXISTS reform_impact (
    reform_impact_id INTEGER PRIMARY KEY AUTO_INCREMENT,
    baseline_policy_id INT NOT NULL,
    reform_policy_id INT NOT NULL, 
    country_id VARCHAR(3) NOT NULL,
    region VARCHAR(32) NOT NULL,
    time_period VARCHAR(32) NOT NULL,
    options_json JSON,
    options_hash VARCHAR(255),
    api_version VARCHAR(10) NOT NULL,
    reform_impact_json JSON NOT NULL,
    status VARCHAR(32) NOT NULL,
    message VARCHAR(255),
    start_time DATETIME
);

"""


_MAX_SIMULATION_RESULTS = 1000
_DEFAULT_SIMULATION_RESULTS = 100


def get_simulations(
    max_results: int | None = 100,
):
    # Get the last N simulations ordered by start time.
    #
    # LIMIT is always applied (unbounded scans against reform_impact
    # are expensive) and max_results is clamped to [1,
    # _MAX_SIMULATION_RESULTS] before being bound as a parameter, so
    # the value can never be interpolated into the SQL string.
    if max_results is None:
        max_results = _DEFAULT_SIMULATION_RESULTS
    try:
        max_results = int(max_results)
    except (TypeError, ValueError):
        max_results = _DEFAULT_SIMULATION_RESULTS
    max_results = max(1, min(max_results, _MAX_SIMULATION_RESULTS))

    result = local_database.query(
        "SELECT * FROM reform_impact ORDER BY start_time DESC LIMIT ?",
        (max_results,),
    ).fetchall()

    # Format into [{}]

    return {"result": [dict(r) for r in result]}
