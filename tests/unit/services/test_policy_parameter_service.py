"""Check a v1 policy's parameter paths against the country model the API runs."""

from __future__ import annotations

from unittest.mock import MagicMock

from policyengine_api.services.policy_parameter_service import (
    PolicyParameterService,
)

KEPT_PARAMETER = "gov.dol.minimum_wage"
REMOVED_PARAMETER = "gov.irs.income.bracket.thresholds.1.WIDOW"
OTHER_REMOVED_PARAMETER = "gov.abolitions.business_rates"
MODEL_PARAMETERS = frozenset(
    {KEPT_PARAMETER, "gov.irs.credits.ctc.amount.base[0].amount"}
)


def _service(model_parameters: frozenset[str] | None = MODEL_PARAMETERS):
    model_parameter_names = MagicMock(return_value=model_parameters)
    return (
        PolicyParameterService(model_parameter_names=model_parameter_names),
        model_parameter_names,
    )


def test_policy_names_each_parameter_the_model_lacks_once_in_order() -> None:
    service, model_parameter_names = _service()

    missing = service.missing_parameters(
        "us",
        {
            REMOVED_PARAMETER: {"2026-01-01.2100-12-31": 0},
            KEPT_PARAMETER: {"2026-01-01.2100-12-31": 9},
            OTHER_REMOVED_PARAMETER: {"2026": True},
        },
    )

    assert missing == [OTHER_REMOVED_PARAMETER, REMOVED_PARAMETER]
    model_parameter_names.assert_called_once_with("us")


def test_policy_whose_parameters_all_exist_lacks_nothing() -> None:
    service, _model_parameter_names = _service()

    assert (
        service.missing_parameters("us", {KEPT_PARAMETER: {"2026-01-01.2100-12-31": 9}})
        == []
    )


def test_empty_policy_lacks_nothing_without_reading_the_model() -> None:
    service, model_parameter_names = _service()

    assert service.missing_parameters("us", {}) == []
    model_parameter_names.assert_not_called()


def test_country_without_a_loaded_model_is_not_checked() -> None:
    service, _model_parameter_names = _service(model_parameters=None)

    assert service.missing_parameters("us", {KEPT_PARAMETER: {"2026": 9}}) is None


def test_policy_json_that_is_not_an_object_is_not_checked() -> None:
    service, model_parameter_names = _service()

    assert service.missing_parameters("us", None) is None
    assert service.missing_parameters("us", ["not", "an", "object"]) is None
    model_parameter_names.assert_not_called()
