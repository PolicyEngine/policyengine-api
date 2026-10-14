"""Whether the API has finished warming up and can serve real requests.

The warmup state defaults to ready for tests and tooling that do not run the
startup warmup. Readiness still requires valid runtime configuration. The
Cloud Run startup path toggles the warmup state around
`policyengine_api.warmup`.
"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_ready = True


def validate_policy_runtime_configuration() -> None:
    """Validate v1 source selectors, v2 persistence, user auth and measurement."""
    from policyengine_api.data.v2.settings import (  # noqa: PLC0415  # keeps importing readiness cheap; only validation needs configuration
        load_v2_runtime_database_settings,
    )
    from policyengine_api.libs.auth0_management import (
        load_auth0_management_settings,
    )
    from policyengine_api.libs.user_auth import (  # noqa: PLC0415  # keeps importing readiness cheap; only validation needs configuration
        load_user_auth_settings,
    )
    from policyengine_api.migration_flags import (  # noqa: PLC0415  # keeps importing readiness cheap; only validation needs configuration
        get_v1_household_read_source,
        get_v1_household_write_source,
        get_v1_policy_read_source,
        get_v1_policy_write_source,
    )
    from policyengine_api.spm import (  # noqa: PLC0415  # keeps importing readiness cheap; only validation needs configuration
        normalize_spm_selection,
    )

    get_v1_policy_write_source()
    get_v1_policy_read_source()
    get_v1_household_write_source()
    get_v1_household_read_source()
    load_v2_runtime_database_settings()
    # User-owned routes fail closed without these settings; an inconsistent
    # or required-but-missing configuration must stop the deployment here.
    load_user_auth_settings()
    load_auth0_management_settings()
    # A bundle whose measurement configuration this build cannot serve would
    # reject every country request. Report it here, where the deployment is
    # gated, instead of only on the requests themselves.
    normalize_spm_selection("us", None)


def mark_not_ready() -> None:
    """Report not-ready — call before running the startup warmup."""
    global _ready  # noqa: PLW0603  # process-wide readiness flag, guarded by _lock
    with _lock:
        _ready = False


def mark_ready() -> None:
    """Report ready — call once the startup warmup has completed."""
    global _ready  # noqa: PLW0603  # process-wide readiness flag, guarded by _lock
    with _lock:
        _ready = True


def is_ready() -> bool:
    """Whether the service is warmed up and can serve a real request quickly."""
    with _lock:
        warmed_up = _ready
    if not warmed_up:
        return False
    try:
        validate_policy_runtime_configuration()
    except (RuntimeError, ValueError):
        return False
    return True
