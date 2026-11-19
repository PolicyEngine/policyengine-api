"""Database-independent validation for v2 dynamic operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.dynamic_parameters import is_dynamic_parameter
from policyengine_api.services.v2.policies.validators import (
    PolicyParametersMissingError,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from uuid import UUID

    from policyengine_api.supported_countries import SupportedCountryId


class DynamicNotFoundError(LookupError):
    """Raised when a dynamic UUID is absent from the selected country."""


class DynamicStorageError(RuntimeError):
    """Raised when the v2 database could not be read or written for a dynamic."""


class DynamicCreationIntegrityError(RuntimeError):
    """Raised when stored dynamic content cannot support safe deduplication."""


class DynamicContentHashCollisionError(DynamicCreationIntegrityError):
    """Raised when equal version/hash keys identify different canonical bytes."""


class DynamicSetsPolicyParametersError(ValueError):
    """Raised when a dynamic sets parameters that are not model assumptions.

    A dynamic holds only parameters under ``gov.simulation.``, plus the US's
    ``simulation.`` (``policyengine_api.dynamic_parameters``); the others
    belong in a policy. ``parameter_names`` lists them, sorted.
    """

    def __init__(self, parameter_names: tuple[str, ...]) -> None:
        """Name each parameter the dynamic may not set."""
        self.parameter_names = parameter_names
        super().__init__(parameter_names)

    def __str__(self) -> str:
        """Say which parameters to send as a policy, and where."""
        return (
            "A dynamic holds only the model's assumptions, the parameters under "
            "gov.simulation (and, in the US, simulation): send the others as a "
            "policy through POST /v2/policies. This dynamic sets: "
            + ", ".join(self.parameter_names)
        )


class DynamicParametersMissingError(PolicyParametersMissingError):
    """Raised when a dynamic sets parameters the running catalog version lacks.

    A calculation refuses it as it refuses such a policy, with the same 422
    and ``missing_parameters``; ``dynamic_id`` names the dynamic (also as
    ``policy_id``, the base error's field).
    """

    @property
    def dynamic_id(self) -> UUID:
        """The dynamic that sets the missing parameters."""
        return self.policy_id

    def __str__(self) -> str:
        """Name the dynamic and each missing parameter."""
        return (
            f"Dynamic {self.policy_id} sets parameters the running catalog "
            f"version does not have: {', '.join(self.missing_parameters)}"
        )


def require_dynamic_parameters(
    country_id: SupportedCountryId, parameter_names: Iterable[str]
) -> None:
    """Raise DynamicSetsPolicyParametersError unless each parameter is an assumption."""
    policy_parameter_names = tuple(
        sorted(
            {
                name
                for name in parameter_names
                if not is_dynamic_parameter(country_id, name)
            }
        )
    )
    if policy_parameter_names:
        raise DynamicSetsPolicyParametersError(policy_parameter_names)


def require_dynamic_parameters_present(
    dynamic_id: UUID, missing_parameters: tuple[str, ...] | None
) -> None:
    """Raise DynamicParametersMissingError when the dynamic sets missing parameters.

    ``missing_parameters`` is a checked dynamic's (``CheckedDynamicRead``):
    None when the running PolicyEngine.py version has no published catalog
    for the country, so nothing could be checked, which passes.
    """
    if missing_parameters:
        raise DynamicParametersMissingError(dynamic_id, missing_parameters)
