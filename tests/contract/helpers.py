from __future__ import annotations

import json
from typing import Any


VOLATILE_STRING = "<volatile>"


def response_json(response) -> dict[str, Any]:
    return json.loads(response.data.decode("utf-8"))


def assert_subset(actual: Any, expected: Any) -> None:
    if expected == VOLATILE_STRING:
        assert actual is not None
        return

    if isinstance(expected, dict):
        assert isinstance(actual, dict)
        for key, expected_value in expected.items():
            assert key in actual
            assert_subset(actual[key], expected_value)
        return

    if isinstance(expected, list):
        assert isinstance(actual, list)
        assert len(actual) >= len(expected)
        for actual_value, expected_value in zip(actual, expected):
            assert_subset(actual_value, expected_value)
        return

    assert actual == expected


def assert_field_path_exists(payload: dict[str, Any], field_path: str) -> None:
    current: Any = payload
    for segment in field_path.split("."):
        if isinstance(current, list):
            assert current, f"{field_path} resolved through an empty list"
            current = current[0]
        assert isinstance(current, dict), (
            f"{field_path} segment {segment} hit {current}"
        )
        assert segment in current
        current = current[segment]
