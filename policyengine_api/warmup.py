"""Warm the simulation machinery at startup so the first real request is fast.

Building a tax-benefit system (at import) does not compile the per-simulation
machinery, so the first calculate on a fresh worker pays a large one-time cost
(~2 minutes for US on Cloud Run). Running a throwaway calculate here moves that
off the first user request, so /readiness-check (via policyengine_api.readiness)
only reports ready once a calculate is actually fast. Only
POLICYENGINE_API_WARMUP_COUNTRIES (default "us") are warmed, to keep the added
boot time inside the startup-probe window.
"""

from __future__ import annotations

import copy
import logging
import os
import time

logger = logging.getLogger(__name__)

# Minimal single-person household requesting household_net_income: computing that
# broad output compiles most of the simulation graph. Period is arbitrary.
_WARMUP_PERIOD = "2025"
WARMUP_HOUSEHOLDS: dict[str, dict] = {
    "us": {
        "people": {"person": {"age": {_WARMUP_PERIOD: 40}}},
        "households": {
            "household": {
                "members": ["person"],
                "household_net_income": {_WARMUP_PERIOD: None},
            }
        },
    },
}


def _requested_countries() -> list[str]:
    raw = os.environ.get("POLICYENGINE_API_WARMUP_COUNTRIES", "us")
    return [country.strip().lower() for country in raw.split(",") if country.strip()]


def run_startup_warmup() -> None:
    """Run a throwaway calculate per configured country (best-effort).

    Failures are logged and swallowed: a warmup error must not stop the worker
    from serving (the first real request would just be slow), and it must never
    leave the service permanently unready.
    """
    from policyengine_api.country import COUNTRIES

    for country_id in _requested_countries():
        household = WARMUP_HOUSEHOLDS.get(country_id)
        country = COUNTRIES.get(country_id)
        if household is None:
            logger.warning("No warmup household for %r; skipping", country_id)
            continue
        if country is None:
            logger.warning("Country %r not loaded; skipping warmup", country_id)
            continue

        started = time.time()
        try:
            country.calculate(copy.deepcopy(household), {})
            logger.info("Warmed up %s in %.1fs", country_id, time.time() - started)
        except Exception:
            logger.exception(
                "Startup warmup calculate failed for %s after %.1fs; continuing "
                "(first real request may be slow)",
                country_id,
                time.time() - started,
            )
