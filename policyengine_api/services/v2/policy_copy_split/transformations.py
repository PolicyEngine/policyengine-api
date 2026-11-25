"""Pure representation transformations for the policy copy split.

A stored copy is split on its own catalog version: its values keep their
parameter IDs, values and dates, and only move to a policy or a dynamic by
``policyengine_api.dynamic_parameters``. Its content hash is a policy's
(``policies.transformations.canonicalize_policy``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.dynamic_parameters import is_dynamic_parameter
from policyengine_api.services.v2.dynamics.types import ResolvedDynamicCreationInput
from policyengine_api.services.v2.policies.transformations import (
    stored_policy_creation_input,
)
from policyengine_api.services.v2.policies.types import ResolvedPolicyCreationInput
from policyengine_api.services.v2.policy_copy_split.types import StoredPolicySplit

if TYPE_CHECKING:
    from collections.abc import Sequence

    from policyengine_api.data.v2.models import (
        ParameterValue,
        Policy,
        TaxBenefitModelVersion,
    )


def split_stored_policy(
    policy: Policy,
    model_version: TaxBenefitModelVersion,
    values: Sequence[tuple[ParameterValue, str]],
) -> StoredPolicySplit | None:
    """Split a stored policy's values, each with its parameter's name, in two.

    The model assumptions go into the dynamic and the rest into the policy,
    which is empty when the copy set only assumptions. Both are bound to the
    copy's own model and catalog version. Return None when the policy sets
    no model assumption.
    """
    whole = stored_policy_creation_input(
        policy, model_version, [value for value, _parameter_name in values]
    )
    names_by_parameter_id = {value.parameter_id: name for value, name in values}
    policy_values = []
    dynamic_values = []
    for value in whole.parameter_values:
        parameter_name = names_by_parameter_id[value.parameter_id]
        if is_dynamic_parameter(whole.country_id, parameter_name):
            dynamic_values.append(value)
        else:
            policy_values.append(value)
    if not dynamic_values:
        return None
    return StoredPolicySplit(
        policy=ResolvedPolicyCreationInput.model_validate(
            {**dict(whole), "parameter_values": policy_values}
        ),
        dynamic=ResolvedDynamicCreationInput.model_validate(
            {**dict(whole), "parameter_values": dynamic_values}
        ),
    )
