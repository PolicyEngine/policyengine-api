"""Validation tests for immutable API v2 policy inputs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from pydantic import ValidationError
import pytest

from policyengine_api.services.v2.policies.types import (
    NativePolicyCreationInput,
    PolicyCreationInput,
    PolicyParameterValueInput,
    ResolvedPolicyCreationInput,
)
from policyengine_api.services.v2.policies.validators import (
    MAXIMUM_POLICY_PARAMETER_VALUES,
)


def _value(**changes) -> dict[str, object]:
    fields: dict[str, object] = {
        "parameter_id": uuid4(),
        "value": {"rate": 0.2, "enabled": True},
        "start_date": "2026-01-01T03:00:00+03:00",
        "end_date": None,
    }
    fields.update(changes)
    return fields


def _command(**changes) -> dict[str, object]:
    fields: dict[str, object] = {
        "country_id": "US",
        "tax_benefit_model_id": uuid4(),
        "parameter_values": [_value()],
    }
    fields.update(changes)
    return fields


def test_input_normalizes_country_and_effective_dates_to_utc() -> None:
    policy_input = PolicyCreationInput.model_validate(_command())

    assert policy_input.country_id == "us"
    assert policy_input.parameter_values[0].start_date == datetime(
        2026,
        1,
        1,
        tzinfo=timezone.utc,
    )


def test_native_and_resolved_inputs_keep_catalog_selection_explicit() -> None:
    native = NativePolicyCreationInput.model_validate(
        {**_command(), "policyengine_version": "5.2.0"}
    )
    resolved = ResolvedPolicyCreationInput.model_validate(
        {
            **native.model_dump(exclude={"policyengine_version"}),
            "policyengine_version": "5.2.0",
            "tax_benefit_model_version_id": uuid4(),
        }
    )

    assert native.policyengine_version == "5.2.0"
    assert resolved.tax_benefit_model_version_id is not None


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
        Decimal("1.2"),
        {1: "non-string key"},
        ("tuple",),
        object(),
    ],
)
def test_non_json_values_are_rejected(value: object) -> None:
    with pytest.raises(ValidationError):
        PolicyParameterValueInput.model_validate(_value(value=value))


def test_json_reference_cycles_are_rejected() -> None:
    cyclic: list[object] = []
    cyclic.append(cyclic)

    with pytest.raises(ValidationError, match="reference cycles"):
        PolicyParameterValueInput.model_validate(_value(value=cyclic))


@pytest.mark.parametrize(
    "changes",
    [
        {"start_date": "2026-01-01T00:00:00"},
        {
            "start_date": "2026-01-02T00:00:00Z",
            "end_date": "2026-01-01T00:00:00Z",
        },
    ],
)
def test_invalid_effective_dates_are_rejected(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PolicyParameterValueInput.model_validate(_value(**changes))


def test_duplicate_parameter_and_normalized_start_date_is_rejected() -> None:
    parameter_id = uuid4()
    first = _value(
        parameter_id=parameter_id,
        start_date="2026-01-01T00:00:00Z",
    )
    duplicate = _value(
        parameter_id=parameter_id,
        start_date="2026-01-01T03:00:00+03:00",
    )

    with pytest.raises(ValidationError, match="parameter_id/start_date"):
        PolicyCreationInput.model_validate(
            _command(parameter_values=[first, duplicate])
        )


def test_parameter_value_count_is_bounded_but_empty_policy_is_valid() -> None:
    assert (
        PolicyCreationInput.model_validate(
            _command(parameter_values=[])
        ).parameter_values
        == []
    )

    repeated = _value()
    parameter_values = [
        {
            **repeated,
            "parameter_id": uuid4(),
            "start_date": datetime(2026, 1, 1, tzinfo=timezone.utc)
            + timedelta(days=index),
        }
        for index in range(MAXIMUM_POLICY_PARAMETER_VALUES + 1)
    ]
    with pytest.raises(ValidationError):
        PolicyCreationInput.model_validate(_command(parameter_values=parameter_values))
