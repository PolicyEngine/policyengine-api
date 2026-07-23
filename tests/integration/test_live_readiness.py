"""Readiness gate for the live deployment smoke suites.

This module is listed FIRST in the "Run staging smoke test" workflow steps so it
runs before the calculate/economy/budget-window suites. The staging services are
scale-to-zero, so a freshly deployed candidate is cold when the suite starts and
needs to import the tax-benefit system (~200s for the US system) before it can
answer a household calculate. The first heavy request would otherwise race that
import against the per-request timeout and fail intermittently — which is exactly
what blocks the downstream production deploy when it does.

Polling /readiness-check here does two things: it proves the deployed revision
actually came up, and it warms the instance so every following test hits a ready
service. It is deliberately a plain, visible test rather than a conftest fixture
so the wait is obvious in the suite output and easy to maintain.
"""

import os
import time

import httpx

# Cloud Run's startup probe allows initialDelaySeconds 180 + failureThreshold 24
# x periodSeconds 10 = 420s before it abandons a boot. Wait a little longer than
# that so a slow-but-valid boot is not reported as a failure here.
READINESS_DEADLINE_SECONDS = float(
    os.environ.get("STAGING_API_READINESS_DEADLINE_SECONDS", "480")
)
READINESS_POLL_INTERVAL_SECONDS = float(
    os.environ.get("STAGING_API_READINESS_POLL_INTERVAL_SECONDS", "5")
)
# Per-request cap: a request that lands mid-boot is held by Cloud Run until the
# instance is ready; bound the individual wait so we keep polling and logging
# progress rather than blocking on a single long request.
READINESS_REQUEST_TIMEOUT_SECONDS = float(
    os.environ.get("STAGING_API_READINESS_REQUEST_TIMEOUT_SECONDS", "30")
)


def test_service_is_ready(api_base_url: str) -> None:
    """Block until the deployed service answers /readiness-check with 200."""
    deadline = time.monotonic() + READINESS_DEADLINE_SECONDS
    attempts = 0
    last_result = "no request completed"

    with httpx.Client(
        base_url=api_base_url,
        timeout=READINESS_REQUEST_TIMEOUT_SECONDS,
        follow_redirects=True,
    ) as client:
        while True:
            attempts += 1
            try:
                response = client.get("/readiness-check")
            except httpx.RequestError as error:
                # Connection/read timeouts while the instance is still importing
                # are expected; keep polling until the deadline.
                last_result = f"{type(error).__name__}: {error}"
            else:
                if response.status_code == 200:
                    return
                last_result = f"HTTP {response.status_code}: {response.text[:200]}"

            if time.monotonic() >= deadline:
                raise AssertionError(
                    f"Service at {api_base_url} did not become ready within "
                    f"{READINESS_DEADLINE_SECONDS:.0f}s ({attempts} attempts); "
                    f"last result was {last_result}"
                )
            time.sleep(READINESS_POLL_INTERVAL_SECONDS)
