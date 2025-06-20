def validate_tracer_analysis_payload(payload: dict):
    # Validate payload
    if not payload:
        return False, "No payload provided"

    required_keys = ["household_id", "policy_id", "variable"]
    for key in required_keys:
        if key not in payload:
            return False, f"Missing required key: {key}"

    # Validate types and formats
    household_id = payload["household_id"]
    policy_id = payload["policy_id"]
    variable = payload["variable"]

    if not isinstance(household_id, (str, int)) or (
        isinstance(household_id, str) and not household_id.isdigit()
    ):
        return False, "household_id must be a numeric integer or string"

    if not isinstance(policy_id, (str, int)) or (
        isinstance(policy_id, str) and not policy_id.isdigit()
    ):
        return False, "policy_id must be a numeric integer or string"

    if not isinstance(variable, str):
        return False, "variable must be a string"

    return True, None
