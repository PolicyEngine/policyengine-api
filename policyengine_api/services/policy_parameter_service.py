"""Check a v1 policy's parameter paths against the country model the API runs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.policies.validators import (
    parameters_missing_from_model,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Container


def loaded_model_parameter_names(country_id: str) -> Container[str] | None:
    """Return the leaf parameter paths of the country model the API runs.

    None for a country without a loaded model. The models load at startup
    (see policyengine_api.warmup); a process that has not loaded them loads
    them here.
    """
    from policyengine_api.country import (  # noqa: PLC0415  # importing country loads every country model; only a check that needs one does
        COUNTRIES,
    )

    country = COUNTRIES.get(country_id)
    return None if country is None else country.parameter_names


class PolicyParameterService:
    """Report which parameters a v1 policy sets that the current model lacks.

    The current model is the country package the Public API runs, whose
    catalog the v2 copy of the same release holds. The comparison is the one
    the v2 copy uses, parameters_missing_from_model. Nothing is read from
    Supabase, so v1 policy reads stay on Cloud SQL.
    """

    def __init__(
        self,
        model_parameter_names: Callable[[str], Container[str] | None] | None = None,
    ) -> None:
        """Read model parameter paths through ``model_parameter_names``.

        Without it, the loaded country models are read.
        """
        self._model_parameter_names = (
            model_parameter_names or loaded_model_parameter_names
        )

    def missing_parameters(
        self, country_id: str, policy_json: object
    ) -> list[str] | None:
        """Return the parameter paths the policy sets that the model lacks, sorted.

        Return None when nothing can be checked: the stored policy is not a
        parameter-path object, or the country has no loaded model.
        """
        if not isinstance(policy_json, dict):
            return None
        if not policy_json:
            return []
        model_parameter_names = self._model_parameter_names(country_id)
        if model_parameter_names is None:
            return None
        return list(parameters_missing_from_model(policy_json, model_parameter_names))
