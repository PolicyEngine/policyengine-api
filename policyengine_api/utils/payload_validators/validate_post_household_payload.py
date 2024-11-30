import json

def validate_post_household_payload(payload):
    """
    Validate the payload for a POST request to set a household's input data.

    Args:
        payload (dict): The payload to validate.

    Returns:
        tuple[bool, str]: A tuple containing a boolean indicating whether the payload is valid and a message.
    """
    # Check that all required keys are present
    required_keys = ["household_json"]
    missing_keys = [key for key in required_keys if key not in payload]
    if missing_keys:
        return False, f"Missing required keys: {missing_keys}"

    # Check that label is either string or None, if present
    if "label" in payload:
        if payload["label"] is not None and not isinstance(
            payload["label"], str
        ):
            return False, "Label must be a string or None"

    # Check that data is a dictionary
    household_dict = json.loads(payload["household_json"])
    if not isinstance(household_dict, dict):
        return False, "Unable to parse household JSON data"

    return True, None




    
    # If label is not string or None, return False
    if not isinstance(payload.get("label"), str) and payload.get("label") is not None:
        return False, "Label must be a string or None."

    if 

    return True, ""




    label = payload.get("label")
    household_json = payload.get("data")
    household_hash = hash_object(household_json)
    api_version = COUNTRY_PACKAGE_VERSIONS.get(country_id)