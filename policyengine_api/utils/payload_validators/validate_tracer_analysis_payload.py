def validate_tracer_analysis_payload(payload: dict):
    # Validate payload
    if not payload:
        return False, "No payload provided"

    required_keys = ["household_id", "policy_id", "variable"]
    for key in required_keys:
        if key not in payload:
            return False, f"Missing required key: {key}"

    return True, None
