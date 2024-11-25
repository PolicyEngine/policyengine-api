import pytest
from typing import Dict, Any, Tuple

from policyengine_api.utils.payload_validators import (
    validate_sim_analysis_payload,
)


@pytest.fixture
def valid_payload() -> Dict[str, Any]:
    return {
        "currency": "USD",
        "selected_version": "v1.0",
        "time_period": "2024",
        "impact": {"value": 100},
        "policy_label": "Test Policy",
        "policy": {"type": "tax", "rate": 0.1},
        "region": "NA",
        "relevant_parameters": ["param1", "param2"],
        "relevant_parameter_baseline_values": [1.0, 2.0],
    }


def test_valid_payload(valid_payload):
    """Test that a valid payload passes validation"""
    is_valid, error = validate_sim_analysis_payload(valid_payload)
    assert is_valid is True
    assert error is None


def test_missing_required_key(valid_payload):
    """Test that missing required keys are detected"""
    del valid_payload["currency"]
    is_valid, error = validate_sim_analysis_payload(valid_payload)
    assert is_valid is False
    assert "Missing required keys: ['currency']" in error


def test_invalid_string_type(valid_payload):
    """Test that wrong type for string fields is detected"""
    valid_payload["currency"] = 123  # Should be string
    is_valid, error = validate_sim_analysis_payload(valid_payload)
    assert is_valid is False
    assert "Key 'currency' must be a string" in error


def test_invalid_dict_type(valid_payload):
    """Test that wrong type for dictionary fields is detected"""
    valid_payload["impact"] = ["not", "a", "dict"]  # Should be dict
    is_valid, error = validate_sim_analysis_payload(valid_payload)
    assert is_valid is False
    assert "Key 'impact' must be a dictionary" in error


def test_invalid_list_type(valid_payload):
    """Test that wrong type for list fields is detected"""
    valid_payload["relevant_parameters"] = "not a list"  # Should be list
    is_valid, error = validate_sim_analysis_payload(valid_payload)
    assert is_valid is False
    assert "Key 'relevant_parameters' must be a list" in error


def test_extra_keys_allowed(valid_payload):
    """Test that extra keys don't cause validation to fail"""
    valid_payload["extra_key"] = "some value"
    is_valid, error = validate_sim_analysis_payload(valid_payload)
    assert is_valid is True
    assert error is None


@pytest.mark.parametrize(
    "key",
    [
        "currency",
        "selected_version",
        "time_period",
        "impact",
        "policy_label",
        "policy",
        "region",
        "relevant_parameters",
        "relevant_parameter_baseline_values",
    ],
)
def test_individual_required_keys(valid_payload, key):
    """Test that each required key is properly checked"""
    del valid_payload[key]
    is_valid, error = validate_sim_analysis_payload(valid_payload)
    assert is_valid is False
    assert f"Missing required keys: ['{key}']" in error
