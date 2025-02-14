def validate_sim_analysis_payload(payload: dict) -> tuple[bool, str | None]:
    # Check if all required keys are present; note
    # that the audience key is optional
    required_keys = [
        "currency",
        "selected_version",
        "time_period",
        "impact",
        "policy_label",
        "policy",
        "region",
        "relevant_parameters",
        "relevant_parameter_baseline_values",
    ]
    str_keys = [
        "currency",
        "selected_version",
        "time_period",
        "policy_label",
        "region",
    ]
    dict_keys = [
        "policy",
        "impact",
    ]
    list_keys = ["relevant_parameters", "relevant_parameter_baseline_values"]
    missing_keys = [key for key in required_keys if key not in payload]
    if missing_keys:
        return False, f"Missing required keys: {missing_keys}"

    # Check if all keys are of the right type
    for key, value in payload.items():
        if key in str_keys and not isinstance(value, str):
            return False, f"Key '{key}' must be a string"
        elif key in dict_keys and not isinstance(value, dict):
            return False, f"Key '{key}' must be a dictionary"
        elif key in list_keys and not isinstance(value, list):
            return False, f"Key '{key}' must be a list"

    return True, None
