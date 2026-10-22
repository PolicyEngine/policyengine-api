"""Refuse to start when the v2 countries table and the country list differ.

Which countries the Public API serves is decided in code
(``policyengine_api.supported_countries``). The v2 ``countries`` table records
what each supports, and must hold one row for each listed country and no
other. ``policyengine_api.asgi`` runs this check while the application loads,
so a disagreement stops the worker before it serves a request.

The check runs only where a v2 runtime database is selected: on Cloud Run
(``K_SERVICE`` is set), or when a v2 runtime database URL or its secret
resource is configured. A local or test startup without v2 configuration
opens no connection.

Startup stops when the database answers and its answer disagrees with the
list: different countries, a missing table, or no privilege to read it.
When the check cannot get an answer, it logs why and startup continues: the
v1 routes do not read the v2 database, and their copies into it already
continue without it. That covers a database that cannot be reached or
refuses the credentials, and v2 configuration that cannot be used, including
a secret that cannot be resolved; the readiness check already reports the
last as not ready, and recovers once the secret resolves.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Protocol

from sqlalchemy.exc import InterfaceError, OperationalError

from policyengine_api.data.v2.settings import (
    V2_RUNTIME_DATABASE_URL,
    V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE,
    V2ConfigurationError,
)
from policyengine_api.supported_countries import SUPPORTED_COUNTRY_IDS

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

logger = logging.getLogger(__name__)

CLOUD_RUN_SERVICE = "K_SERVICE"
V2_RUNTIME_SELECTION_VARIABLES = (
    CLOUD_RUN_SERVICE,
    V2_RUNTIME_DATABASE_URL,
    V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE,
)


class CountryListVerifier(Protocol):
    """Compare the stored countries rows with a list of country IDs."""

    def verify_countries_match_code_list(
        self, listed_country_ids: Iterable[str]
    ) -> None:
        """Raise ``CountryListMismatchError`` unless the rows name exactly these."""
        ...


def _default_country_list_verifier() -> CountryListVerifier:
    from policyengine_api.data.v2.database import get_v2_session_factory
    from policyengine_api.services.v2.countries.database_session import (
        CountryDatabaseSession,
    )
    from policyengine_api.services.v2.countries.services import V2CountryService

    return V2CountryService(CountryDatabaseSession(get_v2_session_factory()))


def v2_runtime_database_selected(environ: Mapping[str, str]) -> bool:
    """Whether this process runs on Cloud Run or has a v2 runtime database."""
    return any(environ.get(name, "").strip() for name in V2_RUNTIME_SELECTION_VARIABLES)


def check_countries_table_at_startup(
    environ: Mapping[str, str] | None = None,
    verifier_factory: Callable[[], CountryListVerifier] | None = None,
) -> None:
    """Raise unless the countries table names exactly the countries in code.

    Raises ``CountryListMismatchError`` on a disagreement and SQLAlchemy's
    ``ProgrammingError`` when the table or the privilege to read it is
    missing. Unusable v2 configuration is logged with its message, which
    never contains a secret, and a database connection failure by its error
    type only, as its detail can name the host; both skip the check.
    """
    values = os.environ if environ is None else environ
    if not v2_runtime_database_selected(values):
        return
    factory = verifier_factory or _default_country_list_verifier
    try:
        factory().verify_countries_match_code_list(SUPPORTED_COUNTRY_IDS)
    except V2ConfigurationError as error:
        logger.warning(
            "Skipped the countries table check at startup: the v2 runtime "
            "configuration cannot be used (%s)",
            error,
        )
    except (OperationalError, InterfaceError) as error:
        logger.warning(
            "Skipped the countries table check at startup: the v2 database "
            "could not be queried (%s)",
            type(error).__name__,
        )
