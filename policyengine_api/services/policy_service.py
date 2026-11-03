"""v1 policy storage: lookup, label search and deduplicated creation.

A new policy may set only parameters that the running country model defines,
with period keys and values that simulations can read; re-saving a policy
identical to a stored one returns the stored policy.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select

from policyengine_api.constants import (
    COUNTRIES,
    COUNTRY_PACKAGE_NAMES,
    COUNTRY_PACKAGE_VERSIONS,
)
from policyengine_api.data.orm import get_v1_session_factory
from policyengine_api.data.v1_models import Policy
from policyengine_api.services.v2.policies.types import LegacyPolicySnapshot
from policyengine_api.services.v2.policies.validators import (
    parameters_missing_from_model,
)
from policyengine_api.utils import hash_object
from policyengine_api.utils.input_validation import UnrecognizedInput
from policyengine_api.utils.policy_data_validation import (
    InvalidPolicyEntry,
    find_invalid_periods_and_values,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Container, Iterator

    from sqlalchemy.orm import Session, sessionmaker

    from policyengine_api.json_types import JSONValue


class InvalidPolicyIdError(Exception):
    """Raised when a policy ID is not a non-negative integer."""


class PolicyNotFoundError(LookupError):
    """Raised when a stored policy does not exist in the requested country.

    ``policy_ids`` holds the ID of each missing policy, so a route that names
    several policies can say which ones were not found. It is empty when the
    caller raised it without IDs because it already knows the policy it asked for.
    """

    def __init__(self, *policy_ids: int) -> None:
        """Keep the IDs of the missing policies, in the order the caller gives."""
        self.policy_ids = policy_ids
        super().__init__(*policy_ids)


_COUNTRY_PACKAGE_NAME_BY_COUNTRY_ID = dict(
    zip(COUNTRIES, COUNTRY_PACKAGE_NAMES, strict=True)
)


class InvalidPolicyDataError(ValueError):
    """Raised when a new policy's data holds entries the country model cannot use.

    ``parameter_paths`` are the paths that are not settable parameters: the
    running country model does not define them, or defines them as a parameter
    group, scale or scale bracket rather than a parameter that holds values.
    ``invalid_entries`` are the period keys and values that simulations cannot
    read (see policyengine_api.utils.policy_data_validation).
    """

    def __init__(
        self,
        country_id: str,
        parameter_paths: tuple[str, ...],
        invalid_entries: tuple[InvalidPolicyEntry, ...] = (),
    ) -> None:
        """Keep the refused paths, sorted, and the refused entries for the 400."""
        self.country_id = country_id
        self.parameter_paths = tuple(sorted(parameter_paths))
        self.invalid_entries = invalid_entries
        message_parts = []
        if self.parameter_paths:
            package_name = _COUNTRY_PACKAGE_NAME_BY_COUNTRY_ID[country_id].replace(
                "_", "-"
            )
            message_parts.append(
                "Policy data contains keys that are not parameters in "
                f"{package_name} {COUNTRY_PACKAGE_VERSIONS[country_id]}: "
                + ", ".join(self.parameter_paths)
            )
        if self.invalid_entries:
            message_parts.append(
                "Policy data contains invalid period keys or values: "
                + " ".join(entry.message for entry in self.invalid_entries)
            )
        super().__init__(". ".join(message_parts))

    @property
    def error_entries(self) -> list[dict]:
        """Return the 400 response's ``errors``: refused paths, then refused entries."""
        return [
            *(
                UnrecognizedInput(
                    input_type="policy_parameter",
                    name=parameter_path,
                    path=f"data.{parameter_path}",
                ).to_dict()
                for parameter_path in self.parameter_paths
            ),
            *(entry.to_dict() for entry in self.invalid_entries),
        ]


@dataclass(frozen=True)
class PolicySetResult:
    """Existing v1 return values and an optional detached mirror snapshot."""

    policy_id: int
    message: str
    is_existing_policy: bool
    snapshot: LegacyPolicySnapshot | None

    def __iter__(self) -> Iterator[int | str | bool]:
        """Preserve the established three-value internal unpacking interface."""
        yield self.policy_id
        yield self.message
        yield self.is_existing_policy


class PolicyService:
    """Policy operations with service-owned ORM transaction boundaries."""

    def __init__(
        self,
        session_factory: sessionmaker[Session] | None = None,
        model_parameter_names: Callable[[str], Container[str] | None] | None = None,
    ) -> None:
        """Use these collaborators, or the defaults for those omitted.

        ``session_factory`` defaults to the application's v1 one.
        ``model_parameter_names`` returns, for a country ID, the leaf parameter
        paths of its model, the parameters a new policy may set, or None when
        the country has no loaded model, which leaves a new policy no
        parameters to set. With it, ``set_policy`` also checks a new policy's
        period keys and values. Without it, ``set_policy`` stores any data;
        the policy route always supplies it.
        """
        self._injected_session_factory = session_factory
        self._model_parameter_names = model_parameter_names

    @property
    def _sessions(self) -> sessionmaker[Session]:
        return self._injected_session_factory or get_v1_session_factory()

    @staticmethod
    def _validate_policy_id(policy_id: int) -> None:
        if type(policy_id) is not int or policy_id < 0:
            msg = f"Invalid policy ID: {policy_id}. Must be a positive integer."
            raise InvalidPolicyIdError(msg)

    def get_policy(
        self,
        country_id: str,
        policy_id: int,
    ) -> Policy | None:
        """Return the stored policy in this country, or None if there is none.

        Raise InvalidPolicyIdError if ``policy_id`` is not a non-negative int, and
        ValueError for an empty ``country_id``.
        """
        self._validate_policy_id(policy_id)
        if not country_id:
            msg = "country_id cannot be empty or None"
            raise ValueError(msg)
        with self._sessions() as session:
            return self._get_policy(session, country_id, policy_id)

    @staticmethod
    def _get_policy(
        session: Session,
        country_id: str,
        policy_id: int,
    ) -> Policy | None:
        return session.scalar(
            select(Policy).where(
                Policy.country_id == country_id,
                Policy.id == policy_id,
            )
        )

    def get_policy_json(
        self,
        country_id: str,
        policy_id: int,
    ) -> JSONValue:
        """Return the policy's stored JSON, or None if the policy does not exist."""
        policy = self.get_policy(country_id, policy_id)
        return None if policy is None else policy.policy_json

    def get_policy_snapshot(
        self,
        country_id: str,
        policy_id: int,
    ) -> LegacyPolicySnapshot | None:
        """Return detached fields required to mirror one existing v1 policy."""
        policy = self.get_policy(country_id, policy_id)
        if policy is None:
            return None
        return LegacyPolicySnapshot(
            country_id=policy.country_id,
            legacy_policy_id=policy.id,
            label=policy.label,
            api_version=policy.api_version,
            policy_json=copy.deepcopy(policy.policy_json),
            source_policy_hash=policy.policy_hash,
        )

    def set_policy(
        self,
        country_id: str,
        label: str | None,
        policy_json: dict,
        *,
        prepare_for_mirroring: bool = False,
    ) -> PolicySetResult:
        """Store a policy, or return the existing one with the same content and label.

        Raise ValueError for an unknown country, and InvalidPolicyDataError when
        a new policy names paths that are not settable parameters, or holds
        period keys or values that simulations cannot read. An existing
        identical policy is returned without checking its data. With
        ``prepare_for_mirroring`` the result carries a snapshot of the stored row,
        for copying the policy into v2.
        """
        country_id = country_id.lower()
        if country_id not in COUNTRY_PACKAGE_VERSIONS:
            msg = f"Invalid country_id: {country_id}"
            raise ValueError(msg)

        policy_hash = hash_object(policy_json)
        with self._sessions.begin() as session:
            policy, message, is_existing_policy = self._set_policy(
                session,
                country_id,
                label,
                policy_json,
                policy_hash,
            )
            # Mirroring must use the database representation of the committed
            # source row. In particular, MySQL JSON can normalize a number's
            # representation during insertion, so the request-side Python
            # object is not necessarily the value a retry will read.
            if prepare_for_mirroring:
                session.refresh(policy)
            snapshot = (
                LegacyPolicySnapshot(
                    country_id=policy.country_id,
                    legacy_policy_id=policy.id,
                    label=policy.label,
                    api_version=policy.api_version,
                    policy_json=copy.deepcopy(policy.policy_json),
                    source_policy_hash=policy.policy_hash,
                )
                if prepare_for_mirroring
                else None
            )
        return PolicySetResult(
            policy_id=policy.id,
            message=message,
            is_existing_policy=is_existing_policy,
            snapshot=snapshot,
        )

    def _set_policy(
        self,
        session: Session,
        country_id: str,
        label: str | None,
        policy_json: dict,
        policy_hash: str,
    ) -> tuple[Policy, str, bool]:
        existing = self._get_unique_policy_with_label(
            session,
            country_id,
            policy_hash,
            label or None,
        )
        if existing is not None:
            return existing, "Policy already exists", True

        self._check_policy_data(country_id, policy_json)
        policy = Policy(
            country_id=country_id,
            label=label,
            policy_json=policy_json,
            policy_hash=policy_hash,
            api_version=COUNTRY_PACKAGE_VERSIONS[country_id],
        )
        session.add(policy)
        session.flush()
        return policy, "Policy created", False

    def _check_policy_data(self, country_id: str, policy_json: dict) -> None:
        """Refuse paths the model lacks, and period keys or values it cannot read.

        Paths are compared as the v2 copy compares them. Every refused path and
        entry is reported in one error.
        """
        if self._model_parameter_names is None or not policy_json:
            return
        model_parameter_names = self._model_parameter_names(country_id) or frozenset()
        unsettable_paths = parameters_missing_from_model(
            policy_json, model_parameter_names
        )
        invalid_entries = find_invalid_periods_and_values(policy_json)
        if unsettable_paths or invalid_entries:
            raise InvalidPolicyDataError(country_id, unsettable_paths, invalid_entries)

    def _get_unique_policy_with_label(
        self,
        session: Session,
        country_id: str,
        policy_hash: str,
        label: str | None,
    ) -> Policy | None:
        return session.scalar(
            select(Policy).where(
                Policy.country_id == country_id,
                Policy.policy_hash == policy_hash,
                Policy.label == label,
            )
        )
