"""Database-independent validation for the policy copy split."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, TypeVar

from policyengine_api.services.v2.dynamics.types import ResolvedDynamicCreationInput
from policyengine_api.services.v2.policies.validators import (
    MAXIMUM_POLICY_PARAMETER_VALUES,
)
from policyengine_api.services.v2.policy_copy_split.types import (
    PolicyCopyRefusalReason,
)

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from policyengine_api.services.v2.policies.types import (
        PolicyParameterValueInput,
        ResolvedPolicyCreationInput,
    )

StoredRow = TypeVar("StoredRow")
# PostgreSQL's lock_not_available (a lock timeout ran out) and deadlock_detected.
LOCK_CONFLICT_SQLSTATES = frozenset({"55P03", "40P01"})


class PolicyCopySplitRefusedError(ValueError):
    """Raised when a copy can't be split as decided; nothing changes for it.

    ``reason`` says why, as the command reports it.
    """

    def __init__(self, reason: PolicyCopyRefusalReason) -> None:
        """Keep the reason, which the command's report names."""
        self.reason = reason
        super().__init__(reason)

    def __str__(self) -> str:
        """Name the reason."""
        return f"the policy copy can't be split: {self.reason.value}"


class PolicyCopyIntegrityError(RuntimeError):
    """Raised when a row the split reads is missing although a key requires it."""


def require_stored_row(row: StoredRow | None, description: str) -> StoredRow:
    """Return the row, or raise PolicyCopyIntegrityError naming what is missing."""
    if row is None:
        msg = f"{description} is missing although a foreign key requires it"
        raise PolicyCopyIntegrityError(msg)
    return row


def _same_value(
    earlier: PolicyParameterValueInput, later: PolicyParameterValueInput
) -> bool:
    """Return whether two values for one parameter and start date are identical.

    The JSON values are compared as JSON, so ``true`` differs from ``1``, which
    Python would count as equal.
    """
    return earlier.end_date == later.end_date and json.dumps(
        earlier.value, sort_keys=True
    ) == json.dumps(later.value, sort_keys=True)


def merge_dynamic_content(
    existing: ResolvedPolicyCreationInput,
    split_off: ResolvedDynamicCreationInput,
) -> ResolvedDynamicCreationInput:
    """Return one dynamic holding a mapping's dynamic and a copy's assumptions.

    ``existing`` is the dynamic a legacy mapping already names, rebuilt from
    its stored rows, and ``split_off`` the model assumptions split from the
    copy the mapping names. A value both set identically for the same
    parameter and start date is kept once. Raise PolicyCopySplitRefusedError
    when they are bound to different models or catalog versions, set one
    parameter for the same start date differently, or hold more values
    together than a dynamic may.
    """
    if (
        existing.country_id,
        existing.tax_benefit_model_id,
        existing.tax_benefit_model_version_id,
    ) != (
        split_off.country_id,
        split_off.tax_benefit_model_id,
        split_off.tax_benefit_model_version_id,
    ):
        raise PolicyCopySplitRefusedError(
            PolicyCopyRefusalReason.DYNAMIC_ON_ANOTHER_CATALOG
        )
    merged: dict[tuple[UUID, datetime], PolicyParameterValueInput] = {
        (value.parameter_id, value.start_date): value
        for value in existing.parameter_values
    }
    for value in split_off.parameter_values:
        identity = (value.parameter_id, value.start_date)
        earlier = merged.get(identity)
        if earlier is None:
            merged[identity] = value
        elif not _same_value(earlier, value):
            raise PolicyCopySplitRefusedError(
                PolicyCopyRefusalReason.CONFLICTING_DYNAMIC_VALUES
            )
    if len(merged) > MAXIMUM_POLICY_PARAMETER_VALUES:
        raise PolicyCopySplitRefusedError(PolicyCopyRefusalReason.TOO_MANY_VALUES)
    return ResolvedDynamicCreationInput.model_validate(
        {**dict(split_off), "parameter_values": list(merged.values())}
    )


def is_lock_conflict(error: BaseException) -> bool:
    """Return whether a database error is a lock timeout or a deadlock.

    SQLAlchemy wraps the driver's error in ``orig``, whose ``sqlstate`` names
    it. A transaction that fails this way changed nothing and can be tried
    again.
    """
    driver_error = getattr(error, "orig", None)
    return getattr(driver_error, "sqlstate", None) in LOCK_CONFLICT_SQLSTATES
