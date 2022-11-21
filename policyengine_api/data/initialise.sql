CREATE TABLE IF NOT EXISTS household (
    id INTEGER PRIMARY KEY,
    country_id VARCHAR(3) NOT NULL,
    label VARCHAR(255),
    api_version VARCHAR(255) NOT NULL,
    household_json JSONB NOT NULL,
    household_hash VARCHAR(255) NOT NULL
);

CREATE TABLE IF NOT EXISTS computed_household (
    household_id INT NOT NULL,
    policy_id INT NOT NULL,
    country_id VARCHAR(3) NOT NULL,
    api_version VARCHAR(10) NOT NULL,
    computed_household_json JSONB NOT NULL,
    PRIMARY KEY (household_id, policy_id, country_id)
);

CREATE TABLE IF NOT EXISTS policy (
    id INTEGER PRIMARY KEY,
    country_id VARCHAR(3) NOT NULL,
    label VARCHAR(255),
    api_version VARCHAR(10) NOT NULL,
    policy_json JSONB NOT NULL,
    policy_hash VARCHAR(255) NOT NULL
);

CREATE TABLE IF NOT EXISTS economy (
    policy_id INT NOT NULL,
    country_id VARCHAR(3) NOT NULL,
    region VARCHAR(32) NOT NULL,
    time_period VARCHAR(32) NOT NULL,
    options_json JSONB NOT NULL,
    api_version VARCHAR(10) NOT NULL,
    economy_json JSONB,
    status VARCHAR(32) NOT NULL,
    PRIMARY KEY (policy_id, country_id, region, time_period, options_json, api_version)
);

CREATE TABLE IF NOT EXISTS reform_impact (
    baseline_policy_id INT NOT NULL,
    reform_policy_id INT NOT NULL,
    country_id VARCHAR(3) NOT NULL,
    region VARCHAR(32) NOT NULL,
    time_period VARCHAR(32) NOT NULL,
    options_json JSONB NOT NULL,
    api_version VARCHAR(10) NOT NULL,
    reform_impact_json JSONB NOT NULL,
    status VARCHAR(32) NOT NULL,
    PRIMARY KEY (baseline_policy_id, reform_policy_id, country_id, region, time_period, options_json, api_version)
);
