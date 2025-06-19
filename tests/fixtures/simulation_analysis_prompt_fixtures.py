from copy import deepcopy

VALID_DATASET_VERSION = "1.1.1"
VALID_MODEL_VERSION = "1.2.3"

valid_input_us = {
    "time_period": "2022",
    "region": "us",
    "dataset": None,
    "currency": "$",
    "policy": {"gov.test.parameter": 0.1},
    "impact": {
        "poverty_by_race": {
            "poverty": {
                "HISPANIC": 0.1,
                "WHITE": 0.2,
            }
        },
        "budget": {
            "baseline": 0.0,
            "reform": 0.1,
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
        "inequality": {
            "baseline": 0.1,
            "reform": 0.2,
        },
        "poverty": {
            "poverty": {
                "baseline": 0.1,
                "reform": 0.2,
            },
            "deep_poverty": {
                "baseline": 0.1,
                "reform": 0.2,
            },
        },
        "poverty_by_gender": {
            "baseline": 0.1,
            "reform": 0.2,
        },
    },
    "relevant_parameters": [
        {
            "parameter1": 100,
            "parameter2": 200,
        }
    ],
    "relevant_parameter_baseline_values": [
        {
            "parameter1": 100,
            "parameter2": 200,
        }
    ],
    "selected_version": "1.2.3",
    "country_id": "us",
    "policy_label": "policy_label",
    "audience": "Normal",
}

valid_input_uk = {
    "time_period": "2022",
    "region": "uk",
    "dataset": None,
    "currency": "£",
    "policy": {"gov.test.parameter": 0.1},
    "impact": {
        "budget": {
            "baseline": 0.0,
            "reform": 0.1,
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
        "inequality": {
            "baseline": 0.1,
            "reform": 0.2,
        },
        "poverty": {
            "poverty": {
                "baseline": 0.1,
                "reform": 0.2,
            },
            "deep_poverty": {
                "baseline": 0.1,
                "reform": 0.2,
            },
        },
        "poverty_by_gender": {
            "baseline": 0.1,
            "reform": 0.2,
        },
    },
    "relevant_parameters": [
        {
            "parameter1": 100,
            "parameter2": 200,
        }
    ],
    "relevant_parameter_baseline_values": [
        {
            "parameter1": 100,
            "parameter2": 200,
        }
    ],
    "selected_version": "1.2.3",
    "country_id": "uk",
    "policy_label": "policy_label",
    "audience": "Normal",
    "dataset_version": VALID_DATASET_VERSION,
    "model_version": VALID_MODEL_VERSION,
}

invalid_data_missing_input_field = {
    k: valid_input_us[k] for k in valid_input_us.keys() - {"time_period"}
}


def given_valid_data_and_dataset_is_enhanced_cps(data):
    modified_data = deepcopy(data)
    modified_data["dataset"] = "enhanced_cps"
    return modified_data
