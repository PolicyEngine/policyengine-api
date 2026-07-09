"""Compare two capture_migration_baseline.py summaries for ramp gates.

This script is intentionally not part of normal CI. It takes a baseline
summary JSON and a candidate summary JSON (both produced by
capture_migration_baseline.py) and exits nonzero unless, for every probe in
the baseline, the candidate's error rate is within --error-rate-margin
(default +0.1pp) and its p95 latency is within --p95-ratio (default x1.20).

Gates are evaluated PER PROBE, never on the pooled summary: pooling mixes
probe populations with very different latency scales, so a shift in mix
masquerades as a regression (or hides one). Simulation-gateway completion
rows are gated as their own pseudo-probe on completion time.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

try:
    # Shared with the baseline tool so "p95" means the same thing across the
    # GAE-vs-Cloud-Run evidence set.
    from scripts.capture_migration_baseline import _percentile
except ImportError:  # direct execution: python scripts/compare_migration_baseline.py
    from capture_migration_baseline import _percentile

COMPLETION_SUFFIX = " (completion)"


@dataclass(frozen=True)
class ProbeStats:
    name: str
    request_count: int
    failure_count: int
    error_rate: float
    p95_latency_ms: float | None


def _stats_by_probe(summary: dict) -> dict[str, ProbeStats]:
    """Recompute per-probe stats from a summary's probes array.

    Request rows (completed is None) group by probe name; completion rows
    (completed True/False) form a separate pseudo-probe gated on
    completion_ms so slow-but-successful completions are still caught.
    """
    groups: dict[str, list[dict]] = {}
    for row in summary.get("probes", []):
        name = row["name"]
        if row.get("completed") is not None:
            name += COMPLETION_SUFFIX
        groups.setdefault(name, []).append(row)

    stats: dict[str, ProbeStats] = {}
    for name, rows in groups.items():
        if name.endswith(COMPLETION_SUFFIX):
            successes = [
                row["completion_ms"]
                for row in rows
                if row.get("completed") and row.get("completion_ms") is not None
            ]
            failure_count = sum(1 for row in rows if not row.get("completed"))
        else:
            successes = [row["latency_ms"] for row in rows if row.get("ok")]
            failure_count = sum(1 for row in rows if not row.get("ok"))
        stats[name] = ProbeStats(
            name=name,
            request_count=len(rows),
            failure_count=failure_count,
            error_rate=failure_count / len(rows),
            p95_latency_ms=_percentile(successes, 0.95),
        )
    return stats


def compare(
    baseline: dict,
    candidate: dict,
    *,
    error_rate_margin: float,
    p95_ratio: float,
) -> tuple[bool, list[str]]:
    """Return (passed, report_lines) for candidate vs baseline."""
    baseline_stats = _stats_by_probe(baseline)
    candidate_stats = _stats_by_probe(candidate)
    lines: list[str] = []
    passed = True

    if not baseline_stats:
        return False, ["FAIL: baseline contains no probes"]

    for name in sorted(baseline_stats):
        base = baseline_stats[name]
        cand = candidate_stats.get(name)
        if cand is None:
            passed = False
            lines.append(f"FAIL {name}: probe missing from candidate")
            continue
        if base.p95_latency_ms is None:
            passed = False
            lines.append(
                f"FAIL {name}: baseline has no successful requests; "
                "recapture the baseline"
            )
            continue

        problems = []
        error_rate_limit = base.error_rate + error_rate_margin
        if cand.error_rate > error_rate_limit + 1e-9:
            problems.append(
                f"error rate {cand.error_rate:.4f} > "
                f"{base.error_rate:.4f} + {error_rate_margin:.4f}"
            )
        p95_limit = base.p95_latency_ms * p95_ratio
        if cand.p95_latency_ms is None:
            problems.append("no successful requests")
        elif cand.p95_latency_ms > p95_limit + 1e-9:
            problems.append(
                f"p95 {cand.p95_latency_ms:.2f}ms > "
                f"{base.p95_latency_ms:.2f}ms x {p95_ratio:.2f}"
            )

        if problems:
            passed = False
            lines.append(f"FAIL {name}: " + "; ".join(problems))
        else:
            lines.append(
                f"PASS {name}: error rate {cand.error_rate:.4f} "
                f"(≤ {error_rate_limit:.4f}), p95 {cand.p95_latency_ms:.2f}ms "
                f"(≤ {p95_limit:.2f}ms)"
            )

    for name in sorted(set(candidate_stats) - set(baseline_stats)):
        lines.append(f"NOTE {name}: not in baseline; not gated")

    return passed, lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Gate a candidate baseline JSON against a reference "
        "baseline JSON, per probe."
    )
    parser.add_argument("baseline", help="reference summary JSON path")
    parser.add_argument("candidate", help="candidate summary JSON path")
    parser.add_argument(
        "--error-rate-margin",
        type=float,
        default=0.001,
        help="allowed error-rate increase over baseline (default 0.001 = 0.1pp)",
    )
    parser.add_argument(
        "--p95-ratio",
        type=float,
        default=1.20,
        help="allowed p95 ratio over baseline (default 1.20)",
    )
    args = parser.parse_args(argv)

    baseline = json.loads(Path(args.baseline).read_text())
    candidate = json.loads(Path(args.candidate).read_text())
    passed, lines = compare(
        baseline,
        candidate,
        error_rate_margin=args.error_rate_margin,
        p95_ratio=args.p95_ratio,
    )
    for line in lines:
        print(line)
    print("RESULT: PASS" if passed else "RESULT: FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
