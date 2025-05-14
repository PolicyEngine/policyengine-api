import math
from pydantic import BaseModel
from typing import Any, Annotated, Optional


class V2V1Comparison(BaseModel):
    """
    The entire v1/v2 comparison log
    """

    country_id: str
    region: str
    reform_policy: Annotated[str, "JSON deserialized to string"]
    baseline_policy: Annotated[str, "JSON deserialized to string"]
    reform_policy_id: int
    baseline_policy_id: int
    time_period: str
    dataset: str
    v1_country_package_version: str
    # v2_country_package_version comes from v2 API results, so unavailable during runtime errors
    v2_country_package_version: str | None = None
    v2_id: str | None = None
    v1_error: Optional[str] = None
    v2_error: Optional[str] = None
    v1_impact: dict[str, Any] | None = None
    v2_impact: dict[str, Any] | None = None
    v1_v2_diff: dict[str, Any] | None = None
    message: Optional[str] = None


def compute_difference(x, y, parent_name: str = ""):
    """
    Computes the difference between two values, recursively for nested structures.

    For numbers (int/float), returns their difference.
    For basic primitives (str, bool, None), returns a formatted string showing both values.
    For lists, recursively computes differences for each element.
    For dictionaries, recursively computes differences for all keys present in either dict.
    Properly handles NaN values.

    Args:
        x: First value to compare
        y: Second value to compare
        parent_name: Path to the current value (for nested structures)

    Returns:
        Various types depending on input:
        - For numbers: their difference (x - y)
        - For primitives: string showing both values
        - For lists: list of differences
        - For dictionaries: dictionary of differences
        - None if values are identical or difference is below threshold
    """
    # Handle None or empty dict values
    if (x is None or x == {}) and (y is None or y == {}):
        return None

    # Handle None values
    if x is None or y is None:
        return f"v1: {x}, v2: {y}"

    # Handle different types
    if type(x) != type(y):
        # Special case for int/float comparison
        if float in ((type(x), type(y))) and int in ((type(x), type(y))):
            # Convert both to float for comparison
            x_float = float(x)
            y_float = float(y)

            # Handle NaN cases
            if math.isnan(x_float) or math.isnan(y_float):
                if math.isnan(x_float) and math.isnan(y_float):
                    return None  # Both are NaN, consider them the same
                return f"v1: {'NaN' if math.isnan(x_float) else x_float}, v2: {'NaN' if math.isnan(y_float) else y_float}"

            diff = x_float - y_float
            # Check if difference is significant (using same threshold as original)
            if abs(diff) < 1e-2 or (
                abs(diff) / abs(x_float) < 0.01 if x_float != 0 else False
            ):
                return None
            return diff
        else:
            return f"v1: {x} (type: {type(x).__name__}), v2: {y} (type: {type(y).__name__})"

    # Handle boolean values
    elif isinstance(x, bool):
        if x == y:
            return None
        return f"v1: {x}, v2: {y}"

    # Handle string values
    elif isinstance(x, str):
        if x == y:
            return None
        return f"v1: {x}, v2: {y}"

    # Handle numeric values
    if isinstance(x, (int, float)):
        # Handle NaN cases
        if isinstance(x, float) and isinstance(y, float):
            if math.isnan(x) or math.isnan(y):
                if math.isnan(x) and math.isnan(y):
                    return None  # Both are NaN, consider them the same
                return f"v1: {'NaN' if math.isnan(x) else x}, v2: {'NaN' if math.isnan(y) else y}"

        diff = x - y

        # Check if difference is significant (using same threshold as original)
        if abs(diff) < 1e-2 or (
            abs(diff) / abs(x) < 0.01 if x != 0 else False
        ):
            return None
        return diff

    # Handle dictionaries
    elif isinstance(x, dict):
        result = {}

        # Convert keys to strings for comparison
        # This is necessary due to type mismatch between API v1 and v2
        # decile result keys
        x_keys_map = {str(k): k for k in x.keys()}
        y_keys_map = {str(k): k for k in y.keys()}

        # Get all unique string representations of keys
        all_str_keys = set(x_keys_map.keys()) | set(y_keys_map.keys())

        for str_k in all_str_keys:
            # Use original keys for access if they exist
            x_original_key = x_keys_map.get(str_k)
            y_original_key = y_keys_map.get(str_k)

            # Determine which key to use in the result (prefer x's key format if available)
            result_key = (
                x_original_key
                if x_original_key is not None
                else y_original_key
            )

            if x_original_key is None:
                # Key only exists in y
                result[result_key] = f"v1: <missing>, v2: {y[y_original_key]}"
            elif y_original_key is None:
                # Key only exists in x
                result[result_key] = f"v1: {x[x_original_key]}, v2: <missing>"
            else:
                # Key exists in both, compare values
                diff = compute_difference(
                    x[x_original_key],
                    y[y_original_key],
                    parent_name=parent_name + "/" + str(result_key),
                )
                if diff is not None:
                    result[result_key] = diff

        return result if result else None

    # Handle lists
    elif isinstance(x, list):
        result = []
        max_len = max(len(x), len(y))

        for i in range(max_len):
            if i < len(x) and i < len(y):
                # Both lists have this index
                diff = compute_difference(
                    x[i], y[i], parent_name=parent_name + f"[{i}]"
                )
                if diff is not None:
                    result.append(diff)
            elif i < len(x):
                # Only in x
                result.append(f"v1: {x[i]}, v2: <missing>")
            else:
                # Only in y
                result.append(f"v1: <missing>, v2: {y[i]}")

        return result if result else None

    # Handle other types
    else:
        if x == y:
            return None
        return f"v1: {x}, v2: {y}"
