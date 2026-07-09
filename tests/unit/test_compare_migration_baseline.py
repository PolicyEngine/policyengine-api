import json

from scripts import capture_migration_baseline, compare_migration_baseline


def _summary(rows):
    return capture_migration_baseline.summarize(rows)


def _probe(name, latency_ms, ok=True, **kwargs):
    return capture_migration_baseline.ProbeResult(
        name=name,
        method="GET",
        path=f"/{name}",
        status_code=200 if ok else 500,
        latency_ms=latency_ms,
        ok=ok,
        **kwargs,
    )


def _baseline_summary():
    return _summary(
        [
            _probe("liveness", 10.0),
            _probe("liveness", 12.0),
            _probe("us_metadata", 100.0),
            _probe("us_metadata", 120.0),
        ]
    )


def test_compare_passes_within_margins():
    candidate = _summary(
        [
            _probe("liveness", 11.0),
            _probe("liveness", 14.0),
            _probe("us_metadata", 110.0),
            _probe("us_metadata", 130.0),
        ]
    )

    passed, lines = compare_migration_baseline.compare(
        _baseline_summary(), candidate, error_rate_margin=0.001, p95_ratio=1.20
    )

    assert passed
    assert all(line.startswith("PASS") for line in lines)


def test_compare_fails_on_p95_regression_in_one_probe_only():
    candidate = _summary(
        [
            _probe("liveness", 11.0),
            _probe("liveness", 12.0),
            _probe("us_metadata", 100.0),
            _probe("us_metadata", 500.0),
        ]
    )

    passed, lines = compare_migration_baseline.compare(
        _baseline_summary(), candidate, error_rate_margin=0.001, p95_ratio=1.20
    )

    assert not passed
    assert any(line.startswith("FAIL us_metadata") for line in lines)
    assert any(line.startswith("PASS liveness") for line in lines)


def test_compare_fails_on_error_rate_regression():
    candidate = _summary(
        [
            _probe("liveness", 11.0),
            _probe("liveness", 12.0, ok=False),
            _probe("us_metadata", 110.0),
            _probe("us_metadata", 120.0),
        ]
    )

    passed, lines = compare_migration_baseline.compare(
        _baseline_summary(), candidate, error_rate_margin=0.001, p95_ratio=1.20
    )

    assert not passed
    assert any(
        line.startswith("FAIL liveness") and "error rate" in line for line in lines
    )


def test_compare_fails_on_probe_missing_from_candidate():
    candidate = _summary([_probe("liveness", 11.0)])

    passed, lines = compare_migration_baseline.compare(
        _baseline_summary(), candidate, error_rate_margin=0.001, p95_ratio=1.20
    )

    assert not passed
    assert any(
        line.startswith("FAIL us_metadata") and "missing" in line for line in lines
    )


def test_compare_gates_completion_rows_as_pseudo_probe():
    def completion(ms, completed=True):
        return _probe(
            "simulation_gateway_completion",
            5.0,
            completion_ms=ms,
            completed=completed,
        )

    baseline = _summary([_probe("liveness", 10.0), completion(1000.0)])
    candidate = _summary([_probe("liveness", 10.0), completion(5000.0)])

    passed, lines = compare_migration_baseline.compare(
        baseline, candidate, error_rate_margin=0.001, p95_ratio=1.20
    )

    assert not passed
    assert any(
        line.startswith("FAIL simulation_gateway_completion (completion)")
        for line in lines
    )


def test_compare_boundary_ratio_passes_exactly_at_limit():
    baseline = _summary([_probe("liveness", 100.0)])
    candidate = _summary([_probe("liveness", 120.0)])

    passed, _ = compare_migration_baseline.compare(
        baseline, candidate, error_rate_margin=0.001, p95_ratio=1.20
    )

    assert passed


def test_compare_fails_on_unusable_baseline():
    baseline = _summary([_probe("liveness", 10.0, ok=False)])
    candidate = _summary([_probe("liveness", 10.0)])

    passed, lines = compare_migration_baseline.compare(
        baseline, candidate, error_rate_margin=0.001, p95_ratio=1.20
    )

    assert not passed
    assert any("recapture the baseline" in line for line in lines)


def test_main_exit_codes_and_output(tmp_path, capsys):
    baseline_path = tmp_path / "baseline.json"
    candidate_path = tmp_path / "candidate.json"
    baseline_path.write_text(json.dumps(_baseline_summary()))
    candidate_path.write_text(json.dumps(_baseline_summary()))

    exit_code = compare_migration_baseline.main(
        [str(baseline_path), str(candidate_path)]
    )

    assert exit_code == 0
    assert "RESULT: PASS" in capsys.readouterr().out

    regression = _summary(
        [
            _probe("liveness", 100.0),
            _probe("liveness", 100.0),
            _probe("us_metadata", 100.0),
            _probe("us_metadata", 5000.0),
        ]
    )
    candidate_path.write_text(json.dumps(regression))

    exit_code = compare_migration_baseline.main(
        [str(baseline_path), str(candidate_path)]
    )

    assert exit_code == 1
    assert "RESULT: FAIL" in capsys.readouterr().out
