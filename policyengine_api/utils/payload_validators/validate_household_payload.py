import json


def validate_household_payload(payload):
    """
    Validate the payload for a POST request to set a household's input data.

    Args:
        payload (dict): The payload to validate.

    Returns:
        tuple[bool, str]: A tuple containing a boolean indicating whether the payload is valid and a message.
    """
    # Check that all required keys are present
    required_keys = ["data"]
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
    if not isinstance(payload["data"], dict):
        return False, "Unable to parse household JSON data"

    return True, None
