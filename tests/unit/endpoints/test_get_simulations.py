"""Regression tests for issue #3451.

get_simulations built its LIMIT via an f-string
(`f"DESC LIMIT {max_results}"`), which is a SQL injection vector
(max_results flows in from a caller) and had no cap, so a tall
integer could drop unbounded rows on a production MySQL. The fix:
always LIMIT, clamp to [1, 1000], and bind as a parameter.
"""

from policyengine_api.endpoints.simulation import get_simulations


def _seed_reform_impacts(test_db, n: int) -> None:
    for i in range(n):
        test_db.query(
            """INSERT INTO reform_impact
            (baseline_policy_id, reform_policy_id, country_id, region, dataset,
             time_period, options_json, options_hash, api_version,
             reform_impact_json, status, start_time, execution_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                i + 1,
                i + 2,
                "us",
                "us",
                "cps",
                "2025",
                "{}",
                f"hash-{i}",
                "1.0.0",
                "{}",
                "complete",
                f"2026-01-01 00:00:{i:02d}",
                f"exec-{i}",
            ),
        )


def test_get_simulations_default_limit_caps_at_100(test_db):
    _seed_reform_impacts(test_db, 150)
    result = get_simulations()
    assert len(result["result"]) == 100


def test_get_simulations_clamps_huge_max_results(test_db):
    _seed_reform_impacts(test_db, 50)
    # A caller passing an absurdly large value must not crash and
    # must not cause a full scan; the value is clamped at 1000.
    result = get_simulations(max_results=10**9)
    assert len(result["result"]) == 50  # only 50 seeded


def test_get_simulations_clamps_negative_max_results(test_db):
    _seed_reform_impacts(test_db, 5)
    # max_results of 0 or negative must still return something sane.
    result = get_simulations(max_results=0)
    assert 1 <= len(result["result"]) <= 5


def test_get_simulations_defaults_when_none(test_db):
    _seed_reform_impacts(test_db, 10)
    result = get_simulations(max_results=None)
    assert len(result["result"]) == 10  # fewer than the default 100


def test_get_simulations_rejects_non_integer_gracefully(test_db):
    _seed_reform_impacts(test_db, 5)
    # A string like "100; DROP TABLE reform_impact" must not reach
    # the SQL statement; it falls back to the default.
    result = get_simulations(max_results="100; DROP TABLE reform_impact")
    assert len(result["result"]) == 5

    # And the table must still exist.
    rows = test_db.query("SELECT COUNT(*) AS c FROM reform_impact").fetchone()
    assert rows["c"] == 5
