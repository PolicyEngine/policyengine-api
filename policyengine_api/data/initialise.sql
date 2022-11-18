CREATE TABLE IF NOT EXISTS household (
    id INTEGER PRIMARY KEY,
    country VARCHAR(3) NOT NULL,
    label VARCHAR(255),
    version VARCHAR(255) NOT NULL,
    household_json JSONB NOT NULL,
    household_hash VARCHAR(255) NOT NULL
);

CREATE TABLE IF NOT EXISTS computed_household (
    household_id INT NOT NULL,
    policy_id INT NOT NULL,
    country VARCHAR(3) NOT NULL,
    version VARCHAR(255) NOT NULL,
    computed_household_json JSONB NOT NULL,
    PRIMARY KEY (household_id, policy_id, country)
);

CREATE TABLE IF NOT EXISTS policy (
    id INTEGER PRIMARY KEY,
    country VARCHAR(3) NOT NULL,
    label VARCHAR(255),
    version VARCHAR(255) NOT NULL,
    policy_json JSONB NOT NULL,
    policy_hash VARCHAR(255) NOT NULL
);

CREATE TABLE IF NOT EXISTS economy (
    policy_id INT NOT NULL,
    country VARCHAR(3) NOT NULL,
    version VARCHAR(255) NOT NULL,
    economy_json JSONB,
    complete BOOLEAN NOT NULL,
    PRIMARY KEY (policy_id, country)
);

CREATE TABLE IF NOT EXISTS reform_impact (
    baseline_policy_id INT NOT NULL,
    reform_policy_id INT NOT NULL,
    country VARCHAR(3) NOT NULL,
    version VARCHAR(255) NOT NULL,
    reform_impact_json JSONB NOT NULL,
    complete BOOLEAN NOT NULL,
    PRIMARY KEY (baseline_policy_id, reform_policy_id, country)
);

-- The policy table should start with one policy: current law.

INSERT INTO policy VALUES (1, "uk", "Current law", "0.1.0", "{}", "current-law")
ON CONFLICT DO NOTHING;

INSERT INTO policy VALUES (1, "us", "Current law", "0.1.0", "{}", "current-law")
ON CONFLICT DO NOTHING;
