"""Warm the simulation machinery at startup so the first real request is fast.

Building a country's tax-benefit system (done at import) does not compile the
per-simulation machinery. The first calculate on a fresh worker otherwise pays a
large one-time cost — measured at ~2 minutes for the US system on Cloud Run — to
materialise the parameter tree and build the first ``Simulation``. Running a
throwaway calculate here moves that cost off the first user request, so
``/readiness-check`` (gated on :mod:`policyengine_api.readiness`) only reports
ready once the service can actually answer a calculate quickly.

Only the countries in ``POLICYENGINE_API_WARMUP_COUNTRIES`` (default ``"us"``) are
warmed, to keep the added boot time inside the Cloud Run startup-probe window.
"""

from __future__ import annotations

import copy
import logging
import os
import time

logger = logging.getLogger(__name__)

# Minimal single-person households whose only requested computation is a broad
# output variable. Computing household_net_income pulls in a large slice of the
# dependency graph, compiling most of the machinery the first real calculate
# would otherwise build on demand. The period is arbitrary — the dominant cost is
# graph/parameter compilation, which carries over to other periods.
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
