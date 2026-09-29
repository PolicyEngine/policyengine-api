from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[2]
DEPLOY = ROOT / "gcp" / "observability"


def test_collector_accepts_only_traces_and_metrics() -> None:
    config = (DEPLOY / "collector" / "config.yaml").read_text()
    assert "telemetry.googleapis.com:443" in config
    assert "memory_limiter" in config
    assert "googleclientauth" in config
    assert "    traces:" in config
    assert "    metrics:" in config
    assert "    logs:\n      receivers:" not in config
