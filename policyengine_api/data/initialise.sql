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
    dataset VARCHAR(255) NOT NULL,
    time_period VARCHAR(32) NOT NULL,
    options_json JSON,
    options_hash VARCHAR(255),
    api_version VARCHAR(10) NOT NULL,
    reform_impact_json JSON NOT NULL,
    status VARCHAR(32) NOT NULL,
    message VARCHAR(255),
    start_time DATETIME,
    execution_id VARCHAR(255) NOT NULL
);

CREATE TABLE IF NOT EXISTS analysis (
    prompt_id INTEGER PRIMARY KEY AUTO_INCREMENT,
    prompt LONGTEXT NOT NULL,
    analysis LONGTEXT,
    status VARCHAR(32) NOT NULL
)

-- The dataset row below was added while the table is in prod;
-- we must allow NULL values for this column
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
    dataset VARCHAR(255),
    number_of_provisions INTEGER NOT NULL,
    api_version VARCHAR(32) NOT NULL,
    added_date BIGINT NOT NULL,
    updated_date BIGINT NOT NULL,
    budgetary_impact VARCHAR(255),
    type VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS user_profiles (
  user_id INTEGER PRIMARY KEY AUTO_INCREMENT,
  auth0_id VARCHAR(255) NOT NULL UNIQUE,
  username VARCHAR(255) UNIQUE,
  primary_country VARCHAR(3) NOT NULL,
  user_since BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS tracers (
  id INTEGER PRIMARY KEY AUTO_INCREMENT,
  household_id INT NOT NULL,
  policy_id INT NOT NULL,
  country_id VARCHAR(3) NOT NULL,
  api_version VARCHAR(10) NOT NULL,
  tracer_output JSON NOT NULL
);

CREATE TABLE IF NOT EXISTS simulations (
    id INTEGER PRIMARY KEY AUTO_INCREMENT,
    country_id VARCHAR(3) NOT NULL,
    api_version VARCHAR(10) NOT NULL,
    -- VARCHAR(255) to accommodate both household IDs and geography codes
    population_id VARCHAR(255) NOT NULL,
    population_type VARCHAR(50) NOT NULL,
    policy_id INT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    output JSON DEFAULT NULL,
    error_message TEXT DEFAULT NULL,
    simulation_spec_json JSON DEFAULT NULL,
    simulation_spec_schema_version INT DEFAULT NULL,
    active_run_id CHAR(36) DEFAULT NULL,
    latest_successful_run_id CHAR(36) DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS report_outputs (
    id INTEGER PRIMARY KEY AUTO_INCREMENT,
    country_id VARCHAR(3) NOT NULL,
    simulation_1_id INT NOT NULL,
    simulation_2_id INT DEFAULT NULL,
    api_version VARCHAR(10) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    output JSON DEFAULT NULL,
    error_message TEXT DEFAULT NULL,
    year VARCHAR(255) DEFAULT '2025',
    report_kind VARCHAR(64) DEFAULT NULL,
    report_spec_json JSON DEFAULT NULL,
    report_spec_schema_version INT DEFAULT NULL,
    report_spec_status VARCHAR(32) DEFAULT NULL,
    active_run_id CHAR(36) DEFAULT NULL,
    latest_successful_run_id CHAR(36) DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS report_output_runs (
    id CHAR(36) PRIMARY KEY,
    report_output_id INT NOT NULL,
    run_sequence INT NOT NULL,
    status VARCHAR(32) NOT NULL,
    output JSON DEFAULT NULL,
    error_message TEXT DEFAULT NULL,
    trigger_type VARCHAR(32) NOT NULL,
    requested_at DATETIME DEFAULT NULL,
    started_at DATETIME DEFAULT NULL,
    finished_at DATETIME DEFAULT NULL,
    source_run_id CHAR(36) DEFAULT NULL,
    report_spec_snapshot_json JSON DEFAULT NULL,
    country_package_version VARCHAR(255) DEFAULT NULL,
    policyengine_version VARCHAR(255) DEFAULT NULL,
    data_version VARCHAR(255) DEFAULT NULL,
    runtime_app_name VARCHAR(255) DEFAULT NULL,
    report_cache_version VARCHAR(255) DEFAULT NULL,
    simulation_cache_version VARCHAR(255) DEFAULT NULL,
    requested_version_override VARCHAR(255) DEFAULT NULL,
    resolved_dataset VARCHAR(255) DEFAULT NULL,
    resolved_options_hash VARCHAR(255) DEFAULT NULL,
    UNIQUE KEY report_output_run_sequence_idx (report_output_id, run_sequence)
);

CREATE TABLE IF NOT EXISTS simulation_runs (
    id CHAR(36) PRIMARY KEY,
    simulation_id INT NOT NULL,
    report_output_run_id CHAR(36) DEFAULT NULL,
    input_position TINYINT DEFAULT NULL,
    run_sequence INT NOT NULL,
    status VARCHAR(32) NOT NULL,
    output JSON DEFAULT NULL,
    error_message TEXT DEFAULT NULL,
    trigger_type VARCHAR(32) NOT NULL,
    requested_at DATETIME DEFAULT NULL,
    started_at DATETIME DEFAULT NULL,
    finished_at DATETIME DEFAULT NULL,
    source_run_id CHAR(36) DEFAULT NULL,
    simulation_spec_snapshot_json JSON DEFAULT NULL,
    country_package_version VARCHAR(255) DEFAULT NULL,
    policyengine_version VARCHAR(255) DEFAULT NULL,
    data_version VARCHAR(255) DEFAULT NULL,
    runtime_app_name VARCHAR(255) DEFAULT NULL,
    simulation_cache_version VARCHAR(255) DEFAULT NULL,
    UNIQUE KEY simulation_run_sequence_idx (simulation_id, run_sequence)
);

CREATE TABLE IF NOT EXISTS legacy_report_output_aliases (
    legacy_report_output_id INT PRIMARY KEY,
    canonical_report_output_id INT NOT NULL
);
