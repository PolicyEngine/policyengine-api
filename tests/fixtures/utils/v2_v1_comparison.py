valid_v2_v1_comparison = {
    "country_id": "us",
    "region": "ca",
    "reform_policy": '{"tax_rate": 0.2}',
    "baseline_policy": '{"tax_rate": 0.15}',
    "reform_policy_id": 1,
    "baseline_policy_id": 7,
    "time_period": "2023-01-01.2028-12-31",
    "dataset": "test_dataset",
    "v2_id": "v2_workflow_id",
    "v2_error": None,
    "v1_country_package_version": "1.0.0",
    "v2_country_package_version": "2.0.0",
    "v1_impact": {"impact_value": 100},
    "v2_impact": {"impact_value": 120},
    "v1_v2_diff": {"impact_value": 20},
    "message": None,
}

invalid_v2_v1_comparison = {
    **valid_v2_v1_comparison,
    "reform_policy_id": "invalid_id",  # Invalid type
}
