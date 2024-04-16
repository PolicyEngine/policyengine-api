CREATE TABLE IF NOT EXISTS household (
    id INTEGER PRIMARY KEY AUTO_INCREMENT,
    country_id VARCHAR(3) NOT NULL,
    label VARCHAR(255),
    api_version VARCHAR(255) NOT NULL,
    household_json JSON NOT NULL,
    household_hash VARCHAR(255) NOT NULL
);

CREATE TABLE IF NOT EXISTS computed_household (
    household_id INT NOT NULL,
    policy_id INT NOT NULL,
    country_id VARCHAR(3) NOT NULL,
    api_version VARCHAR(10) NOT NULL,
    computed_household_json JSON NOT NULL,
    status VARCHAR(32),
    PRIMARY KEY (household_id, policy_id, country_id)
);

CREATE TABLE IF NOT EXISTS policy (
    id INTEGER AUTO_INCREMENT,
    country_id VARCHAR(3) NOT NULL,
    label VARCHAR(255),
    api_version VARCHAR(10) NOT NULL,
    policy_json JSON NOT NULL,
    policy_hash VARCHAR(255) NOT NULL,
    PRIMARY KEY (id, country_id, policy_hash)
);

CREATE TABLE IF NOT EXISTS economy (
    economy_id INTEGER PRIMARY KEY AUTO_INCREMENT,
    policy_id INT NOT NULL,
    country_id VARCHAR(3) NOT NULL,
    region VARCHAR(32),
    time_period VARCHAR(32),
    options_json JSON NOT NULL,
    options_hash VARCHAR(255) NOT NULL,
    api_version VARCHAR(10) NOT NULL,
    economy_json JSON,
    status VARCHAR(32) NOT NULL,
    message VARCHAR(255)
);

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

CREATE TABLE IF NOT EXISTS analysis (
    prompt_id INTEGER PRIMARY KEY AUTO_INCREMENT,
    prompt LONGTEXT NOT NULL,
    analysis LONGTEXT,
    status VARCHAR(32) NOT NULL
)

CREATE TABLE IF NOT EXISTS user_policies (
    id INTEGER PRIMARY KEY AUTO_INCREMENT,
    country_id VARCHAR(3) NOT NULL,
    reform_id INTEGER NOT NULL,
    reform_label VARCHAR(255),
    baseline_id INTEGER NOT NULL,
    baseline_label VARCHAR(255),
    user_id VARCHAR(255) NOT NULL,
    year VARCHAR(32) NOT NULL,
    geography VARCHAR(255) NOT NULL,
    number_of_provisions INTEGER NOT NULL,
    api_version VARCHAR(32) NOT NULL,
    added_date DATETIME NOT NULL,
    updated_date DATETIME NOT NULL,
    budgetary_cost VARCHAR(255),
    type VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS user_profiles (
  id INTEGER PRIMARY KEY AUTO_INCREMENT,
  auth0_id VARCHAR(255) NOT NULL UNIQUE,
  username VARCHAR(255) UNIQUE,
  primary_country VARCHAR(3) NOT NULL,
  user_since DATETIME NOT NULL
);