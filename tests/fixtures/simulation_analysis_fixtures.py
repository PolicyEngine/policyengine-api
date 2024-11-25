test_impact = {
    "budget": 1000,
    "intra_decile": 0.1,
    "decile": 0.2,
    "poverty": {
        "poverty": 0.3,
        "deep_poverty": 0.4,
    },
    "poverty_by_gender": 0.5,
    "poverty_by_race": {"poverty": 0.6},
    "inequality": 0.7,
}

test_json = {
    "currency": "USD",
    "selected_version": "2023",
    "time_period": "2023",
    "impact": test_impact,
    "policy_label": "Test Policy",
    "policy": dict(policy_json="policy details"),
    "region": "US",
    "relevant_parameters": ["param1", "param2"],
    "relevant_parameter_baseline_values": [
        {"param1": 100},
        {"param2": 200},
    ],
    "audience": "Normal",
}
