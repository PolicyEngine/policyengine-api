"""Closed-loop load generator for Cloud Run capacity qualification (migration PR 4, Stage 2).

Not part of CI. Drives a fixed number of closed-loop clients (each waits for its
response before sending the next request) against a deployed API base URL with a
mix of GET /us/metadata and POST /us/calculate requests, and prints a JSON
summary to stdout. Achieved RPS is an output — the capacity signal — not an input.

/us/calculate responses are Redis-cached for 300s keyed on the SHA-256 of the
full request body, while the handler only reads the household/policy keys, so a
top-level nonce field busts the cache without changing the computation. Cells
that measure engine capacity must run with --cache-bust always (the default).
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
from collections import Counter
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

METADATA_PATH = "/us/metadata"
CALCULATE_PATH = "/us/calculate"
READINESS_PATH = "/readiness-check"

OUTCOME_OK = "ok"
OUTCOME_HTTP_4XX = "http_4xx"
OUTCOME_HTTP_429 = "http_429"
OUTCOME_HTTP_5XX = "http_5xx"
OUTCOME_TIMEOUT = "timeout"
OUTCOME_CONNECT_ERROR = "connect_error"


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    index = round((len(values) - 1) * percentile)
    return round(sorted(values)[index], 2)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _classify(status_code: int) -> str:
    if status_code == 429:
        return OUTCOME_HTTP_429
    if status_code >= 500:
        return OUTCOME_HTTP_5XX
    if status_code >= 400:
        return OUTCOME_HTTP_4XX
    return OUTCOME_OK


async def _wait_for_readiness(
    client: httpx.AsyncClient, timeout_seconds: float
) -> float:
    """Poll the readiness endpoint until it answers; return seconds waited."""
    started = time.monotonic()
    while True:
        waited = time.monotonic() - started
        if waited > timeout_seconds:
            raise RuntimeError(
                f"{READINESS_PATH} not ready after {timeout_seconds:.0f}s"
            )
        try:
            response = await client.get(READINESS_PATH, timeout=20.0)
            if response.status_code == 200:
                return waited
        except httpx.HTTPError:
            pass
        await asyncio.sleep(5.0)


async def _client_loop(
    *,
    client_index: int,
    client: httpx.AsyncClient,
    args: argparse.Namespace,
    base_payload: dict,
    cache_bust: bool,
    warmup_until: float,
    deadline: float,
    records: list[dict],
) -> None:
    rng = random.Random(args.seed * 1000 + client_index)
    seq = 0
    while time.monotonic() < deadline:
        seq += 1
        is_calculate = rng.random() < args.calculate_share
        if is_calculate:
            payload = copy.deepcopy(base_payload)
            if cache_bust:
                payload["_loadtest"] = f"{args.cell_label}-{client_index}-{seq}"
            method, path = "POST", CALCULATE_PATH
            timeout = args.timeout_calculate
        else:
            payload = None
            method, path = "GET", METADATA_PATH
            timeout = args.timeout_metadata

        warmup = time.monotonic() < warmup_until
        started = time.perf_counter()
        status = 0
        try:
            response = await client.request(method, path, json=payload, timeout=timeout)
            status = response.status_code
            outcome = _classify(status)
        except httpx.TimeoutException:
            outcome = OUTCOME_TIMEOUT
        except httpx.HTTPError:
            outcome = OUTCOME_CONNECT_ERROR
        records.append(
            {
                "endpoint": "calculate" if is_calculate else "metadata",
                "warmup": warmup,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "status": status,
                "outcome": outcome,
            }
        )


def _summarize_endpoint(records: list[dict], duration_seconds: float) -> dict:
    latencies = [r["latency_ms"] for r in records if r["outcome"] == OUTCOME_OK]
    outcome_counts = Counter(r["outcome"] for r in records)
    status_counts = Counter(str(r["status"]) for r in records)
    return {
        "request_count": len(records),
        "achieved_rps": round(len(records) / duration_seconds, 3),
        "p50_latency_ms": _percentile(latencies, 0.50),
        "p90_latency_ms": _percentile(latencies, 0.90),
        "p95_latency_ms": _percentile(latencies, 0.95),
        "p99_latency_ms": _percentile(latencies, 0.99),
        "max_latency_ms": max(latencies) if latencies else None,
        "outcome_counts": dict(outcome_counts),
        "status_counts": dict(status_counts),
    }


async def _run(args: argparse.Namespace) -> dict:
    base_payload = json.loads(Path(args.calculate_payload).read_text())
    base_payload["household"]["axes"][0][0]["count"] = args.axes_count
    cache_bust = args.cache_bust == "always"

    limits = httpx.Limits(max_connections=args.clients + 2)
    async with httpx.AsyncClient(
        base_url=args.base_url.rstrip("/"), limits=limits
    ) as client:
        readiness_wait = await _wait_for_readiness(client, args.readiness_timeout)
        # One throwaway calculate so first-touch code paths are warm before timing.
        throwaway = copy.deepcopy(base_payload)
        throwaway["_loadtest"] = f"{args.cell_label}-throwaway"
        await client.post(
            CALCULATE_PATH, json=throwaway, timeout=args.timeout_calculate
        )

        records: list[dict] = []
        started_at = _utc_now_iso()
        start = time.monotonic()
        warmup_until = start + args.warmup_seconds
        deadline = warmup_until + args.duration_seconds
        await asyncio.gather(
            *(
                _client_loop(
                    client_index=i,
                    client=client,
                    args=args,
                    base_payload=base_payload,
                    cache_bust=cache_bust,
                    warmup_until=warmup_until,
                    deadline=deadline,
                    records=records,
                )
                for i in range(args.clients)
            )
        )
        ended_at = _utc_now_iso()

    measured = [r for r in records if not r["warmup"]]
    summary = {
        "cell": args.cell_label,
        "base_url": args.base_url,
        "clients": args.clients,
        "duration_seconds": args.duration_seconds,
        "warmup_seconds": args.warmup_seconds,
        "calculate_share": args.calculate_share,
        "axes_count": args.axes_count,
        "cache_bust": args.cache_bust,
        "seed": args.seed,
        "readiness_wait_seconds": round(readiness_wait, 1),
        "started_at_utc": started_at,
        "ended_at_utc": ended_at,
        "warmup_request_count": len(records) - len(measured),
        "measured_request_count": len(measured),
        "endpoints": {
            endpoint: _summarize_endpoint(
                [r for r in measured if r["endpoint"] == endpoint],
                args.duration_seconds,
            )
            for endpoint in ("metadata", "calculate")
        },
    }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--cell-label", required=True)
    parser.add_argument("--clients", type=int, default=4)
    parser.add_argument("--duration-seconds", type=float, default=600.0)
    parser.add_argument("--warmup-seconds", type=float, default=60.0)
    parser.add_argument("--calculate-share", type=float, default=0.3)
    parser.add_argument("--axes-count", type=int, default=101)
    parser.add_argument(
        "--cache-bust",
        choices=("always", "never"),
        default="always",
        help="always = every calculate does real engine work (capacity cells); "
        "never = identical payloads measure the Redis cache path",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--calculate-payload", default="tests/data/calculate_us_1_data.json"
    )
    parser.add_argument("--timeout-calculate", type=float, default=290.0)
    parser.add_argument("--timeout-metadata", type=float, default=60.0)
    parser.add_argument(
        "--readiness-timeout",
        type=float,
        default=420.0,
        help="seconds to wait for /readiness-check (cold imports take ~3 min)",
    )
    args = parser.parse_args()

    summary = asyncio.run(_run(args))
    json.dump(summary, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
