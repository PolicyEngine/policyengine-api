"""Framework-independent data exchanged by v2 dynamic layers.

A dynamic's content has a policy's fields, is bound to one catalog version
as a policy is, and is hashed by the same canonical document
(``policies.transformations.canonical_policy_document``). It differs in two
ways: it sets at least one value, since "no assumptions beyond the model's
defaults" is ``dynamic_id`` null, and it holds only the model's assumptions
(``policyengine_api.dynamic_parameters``), which ``dynamics.validators``
checks once the catalog has named the parameters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

from pydantic import Field

from policyengine_api.query_parameters import PolicyEngineVersion
from policyengine_api.services.v2.policies.types import (
    ParameterValueInputs,
    PolicyCreationInput,
    PolicyRead,
    ResolvedPolicyCreationInput,
)

if TYPE_CHECKING:
    from uuid import UUID

# A dynamic's values: at least one, and at most as many as a policy's.
DynamicParameterValueInputs = Annotated[
    ParameterValueInputs,
    Field(
        min_length=1,
        description=(
            "The model assumptions the dynamic sets, by catalog parameter ID: "
            "parameters under gov.simulation, plus simulation in the US and "
            "gov.dynamic in the UK. "
            "At least one: for none, send dynamic_id null."
        ),
    ),
]


class DynamicCreationInput(PolicyCreationInput):
    """Complete immutable dynamic content accepted from any source."""

    parameter_values: DynamicParameterValueInputs


class NativeDynamicCreationInput(DynamicCreationInput):
    """Native dynamic content plus an optional catalog-version selection."""

    policyengine_version: PolicyEngineVersion | None = None


class ResolvedDynamicCreationInput(ResolvedPolicyCreationInput):
    """Dynamic content bound to one exact initialized catalog version."""

    parameter_values: DynamicParameterValueInputs


@dataclass(frozen=True)
class DynamicCreationResult:
    """New or deduplicated immutable dynamic identity."""

    dynamic_id: UUID
    created: bool


@dataclass(frozen=True)
class DynamicRead(PolicyRead):
    """A stored v2 dynamic with its parameter values, as returned to routes.

    It has a policy's fields, read from ``dynamics`` instead of ``policies``.
    """


@dataclass(frozen=True)
class CheckedDynamicRead(DynamicRead):
    """A stored dynamic checked against the running catalog, as routes return it.

    ``missing_parameters`` lists the parameter names the dynamic sets that the
    running catalog lacks, sorted; it is None only when the running
    PolicyEngine.py version has no published catalog for the country.
    """

    missing_parameters: tuple[str, ...] | None


@dataclass(frozen=True)
class NativeDynamicCreation:
    """Complete dynamic read plus whether this request inserted it."""

    item: CheckedDynamicRead
    created: bool
