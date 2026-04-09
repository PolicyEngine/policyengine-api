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


def get_simulations(
    max_results: int = 100,
):
    # Get the last N simulations ordered by start time

    desc_limit = f"DESC LIMIT {max_results}" if max_results is not None else ""

    result = local_database.query(
        f"SELECT * FROM reform_impact ORDER BY start_time {desc_limit}",
    ).fetchall()

    # Format into [{}]

    return {"result": [dict(r) for r in result]}
