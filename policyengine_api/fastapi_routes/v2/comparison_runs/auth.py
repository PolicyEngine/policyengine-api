"""Google service-account authentication for internal Stage 12 persistence."""

from __future__ import annotations

import os

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token


STAGE12_PERSISTENCE_AUDIENCE = "https://policyengine.org/internal/stage12-persistence"
_BEARER = HTTPBearer(auto_error=False)
_ALLOWED_CALLERS = {
    "staging": frozenset(
        {
            "sim-entry-beta-runtime@policyengine-simulation-entry.iam.gserviceaccount.com",
            "stage12-modal-staging@policyengine-simulation-entry.iam.gserviceaccount.com",
        }
    ),
    "production": frozenset(
        {
            "sim-entry-prod-runtime@policyengine-simulation-entry.iam.gserviceaccount.com",
            "stage12-modal-production@policyengine-simulation-entry.iam.gserviceaccount.com",
        }
    ),
}


class Stage12PersistenceAuthenticator:
    """Allow only the provisioned simulation identities for this environment."""

    def __call__(
        self,
        credentials: HTTPAuthorizationCredentials | None = Depends(_BEARER),
    ) -> None:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

        environment = os.environ.get("DEPLOYMENT_ENVIRONMENT", "")
        allowed_callers = _ALLOWED_CALLERS.get(environment)
        if allowed_callers is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        try:
            claims = id_token.verify_oauth2_token(
                credentials.credentials,
                GoogleAuthRequest(),
                audience=STAGE12_PERSISTENCE_AUDIENCE,
            )
        except (GoogleAuthError, ValueError, TypeError) as error:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN) from error

        caller = claims.get("email")
        if claims.get("email_verified") is not True or caller not in allowed_callers:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
