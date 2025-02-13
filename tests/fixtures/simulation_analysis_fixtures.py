test_impact = {
    "budget": {
        "baseline": 0.0,
        "reform": 0.1,
        "change": 0.2,
    },
    "intra_decile": {
        "baseline": {
            "1": 0.1,
            "2": 0.2,
            "3": 0.3,
            "4": 0.4,
            "5": 0.5,
            "6": 0.6,
            "7": 0.7,
            "8": 0.8,
            "9": 0.9,
            "10": 1.0,
        },
        "reform": {
            "1": 0.1,
            "2": 0.2,
            "3": 0.3,
            "4": 0.4,
            "5": 0.5,
            "6": 0.6,
            "7": 0.7,
            "8": 0.8,
            "9": 0.9,
            "10": 1.0,
        },
    },
    "decile": {
        "1": 0.1,
        "2": 0.2,
        "3": 0.3,
        "4": 0.4,
        "5": 0.5,
        "6": 0.6,
        "7": 0.7,
        "8": 0.8,
        "9": 0.9,
        "10": 1.0,
    },
    "poverty": {
        "poverty": 0.3,
        "deep_poverty": 0.4,
    },
    "poverty_by_gender": {
        "baseline": {
            "male": 0.5,
            "female": 0.6,
        },
        "reform": {
            "male": 0.7,
            "female": 0.8,
        },
    },
    "poverty_by_race": {"poverty": 0.6},
    "inequality": {
        "baseline": 0.7,
        "reform": 0.8,
        "change": 0.9,
    },
}

test_json = {
    "currency": "USD",
    "selected_version": "2023",
    "time_period": "2023",
    "impact": test_impact,
    "policy_label": "Test Policy",
    "policy": dict(policy_json="policy details"),
    "region": "US",
    "relevant_parameters": [
        {"param1": 100},
        {"param2": 200},
    ],
    "relevant_parameter_baseline_values": [
        {"param1": 100},
        {"param2": 200},
    ],
    "audience": "Normal",
}
