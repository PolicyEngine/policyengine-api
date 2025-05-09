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
    v2_id: str | None = None
    v2_error: Optional[str]
    v1_impact: dict[str, Any] | None = None
    v2_impact: dict[str, Any] | None = None
    v1_v2_diff: dict[str, Any] | None = None
    message: Optional[str]


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
        # Check all keys in either dictionary
        all_keys = set(x.keys()) | set(y.keys())
        for k in all_keys:
            if k not in x:
                result[k] = f"v1: <missing>, v2: {y[k]}"
            elif k not in y:
                result[k] = f"v1: {x[k]}, v2: <missing>"
            else:
                # Recursively compute difference for this key
                diff = compute_difference(
                    x[k], y[k], parent_name=parent_name + "/" + str(k)
                )
                if diff is not None:
                    result[k] = diff

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
