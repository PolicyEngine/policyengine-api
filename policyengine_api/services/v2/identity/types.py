"""Framework-independent data exchanged by v2 identity layers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints


IdentityText = Annotated[str, StringConstraints(min_length=1)]
IdentityEmail = Annotated[str, StringConstraints(min_length=1, max_length=320)]


class UserPrincipal(BaseModel):
    """A verified external sign-in identity; never derived from request data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    issuer: IdentityText
    subject: IdentityText
    email: IdentityEmail | None = None


@dataclass(frozen=True)
class ResolvedUser:
    """The v2 user that owns one verified sign-in identity.

    ``provisioned`` is true only when this resolution inserted the user and
    identity rows. A concurrent request that lost the insert race and read the
    winner's rows back resolves with ``provisioned`` false.
    """

    user_id: UUID
    email: str | None
    provisioned: bool
