"""Application sequencing for validated immutable policy creation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from sqlmodel import Session

from policyengine_api.constants import POLICYENGINE_VERSION
from policyengine_api.data.v2.policies.creates import (
    create_parameter_values,
    create_policy,
)
from policyengine_api.data.v2.policies.reads import (
    read_policy_by_content_identity,
    read_policy_catalog,
    read_stored_policy_command,
    read_version_parameter_ids,
)
from policyengine_api.services.v2.policies.canonicalization import (
    CanonicalPolicyContent,
    canonical_policy_document,
    canonicalize_policy,
)
from policyengine_api.services.v2.policies.catalog_validation import (
    validate_policy_catalog,
)
from policyengine_api.services.v2.policies.commands import (
    PolicyCreateCommand,
    ResolvedPolicyCreateCommand,
)


class PolicyCreationIntegrityError(RuntimeError):
    """Raised when stored policy content cannot support safe deduplication."""


class PolicyContentHashCollisionError(PolicyCreationIntegrityError):
    """Raised when equal version/hash keys identify different canonical bytes."""


@dataclass(frozen=True)
class PolicyCreationResult:
    """New or deduplicated immutable policy identity."""

    policy_id: UUID
    created: bool


def resolve_policy_catalog(
    session: Session,
    command: PolicyCreateCommand,
    *,
    policyengine_version: str | None = None,
    running_policyengine_version: str = POLICYENGINE_VERSION,
) -> ResolvedPolicyCreateCommand:
    """Read and validate the exact catalog selected for policy creation."""

    selected = read_policy_catalog(
        session,
        command.country_id,
        policyengine_version=policyengine_version,
        running_policyengine_version=running_policyengine_version,
    )
    requested_parameter_ids = {value.parameter_id for value in command.parameter_values}
    resolved_parameter_ids = read_version_parameter_ids(
        session,
        model_version_id=selected.model_version.id,
        requested_ids=requested_parameter_ids,
    )
    return validate_policy_catalog(
        command,
        selected=selected,
        resolved_parameter_ids=resolved_parameter_ids,
    )


def create_resolved_policy(
    session: Session,
    command: ResolvedPolicyCreateCommand,
    *,
    canonicalizer: Callable[
        [ResolvedPolicyCreateCommand], CanonicalPolicyContent
    ] = canonicalize_policy,
) -> PolicyCreationResult:
    """Create one policy or verify and return equivalent stored content."""

    content = canonicalizer(command)
    created_policy_id = create_policy(
        session,
        command,
        canonicalization_version=content.version,
        content_hash=content.content_hash,
    )
    if created_policy_id is not None:
        create_parameter_values(
            session,
            policy_id=created_policy_id,
            command=command,
        )
        return PolicyCreationResult(policy_id=created_policy_id, created=True)

    existing = read_policy_by_content_identity(
        session,
        canonicalization_version=content.version,
        content_hash=content.content_hash,
    )
    if existing is None:
        raise PolicyCreationIntegrityError(
            "policy hash conflict did not resolve to a stored policy"
        )
    stored_command = read_stored_policy_command(session, existing)
    if stored_command is None:
        raise PolicyCreationIntegrityError(
            "stored policy references an absent model version"
        )
    if canonical_policy_document(stored_command) != content.document:
        raise PolicyContentHashCollisionError(
            "stored policy content differs for the same canonical version and hash"
        )
    return PolicyCreationResult(policy_id=existing.id, created=False)
