from pathlib import Path

from policyengine_api.constants import REPO


def _column_names(test_db, table_name: str) -> set[str]:
    rows = test_db.query(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def test_stage_one_run_schema_is_initialized_in_local_test_db(test_db):
    report_output_columns = _column_names(test_db, "report_outputs")
    assert {
        "report_kind",
        "report_spec_json",
        "report_spec_schema_version",
        "report_spec_status",
        "report_identity_hash",
        "report_identity_schema_version",
        "active_run_id",
        "latest_successful_run_id",
    }.issubset(report_output_columns)

    simulation_columns = _column_names(test_db, "simulations")
    assert {
        "simulation_spec_json",
        "simulation_spec_schema_version",
        "active_run_id",
        "latest_successful_run_id",
    }.issubset(simulation_columns)

    report_run_columns = _column_names(test_db, "report_output_runs")
    assert {
        "id",
        "report_output_id",
        "run_sequence",
        "trigger_type",
        "report_spec_snapshot_json",
        "country_package_version",
        "policyengine_version",
        "data_version",
        "runtime_app_name",
        "report_cache_version",
        "simulation_cache_version",
        "requested_version_override",
        "resolved_dataset",
        "resolved_options_hash",
    }.issubset(report_run_columns)

    simulation_run_columns = _column_names(test_db, "simulation_runs")
    assert {
        "id",
        "simulation_id",
        "report_output_run_id",
        "input_position",
        "run_sequence",
        "trigger_type",
        "simulation_spec_snapshot_json",
        "country_package_version",
        "policyengine_version",
        "data_version",
        "runtime_app_name",
        "simulation_cache_version",
    }.issubset(simulation_run_columns)

    alias_columns = _column_names(test_db, "legacy_report_output_aliases")
    assert {"legacy_report_output_id", "canonical_report_output_id"} == alias_columns


def test_stage_one_schema_is_defined_in_both_sql_initializers():
    sql_paths = [
        REPO / "policyengine_api" / "data" / "initialise.sql",
        REPO / "policyengine_api" / "data" / "initialise_local.sql",
    ]

    required_snippets = [
        "CREATE TABLE IF NOT EXISTS report_output_runs",
        "CREATE TABLE IF NOT EXISTS simulation_runs",
        "CREATE TABLE IF NOT EXISTS legacy_report_output_aliases",
        "report_spec_json",
        "report_spec_status",
        "report_identity_hash",
        "report_identity_schema_version",
        "simulation_spec_json",
        "active_run_id",
        "latest_successful_run_id",
    ]

    for sql_path in sql_paths:
        sql_text = Path(sql_path).read_text()
        for snippet in required_snippets:
            assert snippet in sql_text, f"{snippet} missing from {sql_path.name}"
