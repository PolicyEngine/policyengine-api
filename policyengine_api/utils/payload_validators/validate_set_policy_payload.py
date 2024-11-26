def validate_set_policy_payload(payload: dict) -> tuple[bool, str | None]:
    
    # Check that all required keys are present
    required_keys = ["data"]
    missing_keys = [key for key in required_keys if key not in payload]
    if missing_keys:
        return False, f"Missing required keys: {missing_keys}"

    # Check that label is either string or None
    if "label" in payload:
        if payload["label"] is not None and not isinstance(payload["label"], str):
            return False, "Label must be a string or None"
        
    # Check that data is a dictionary
    if not isinstance(payload["data"], dict):
        return False, "Data must be a dictionary"
    
    return True, None