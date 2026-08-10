"""Regression tests for issue #3451.

get_simulations built its LIMIT via an f-string
(`f"DESC LIMIT {max_results}"`), which is a SQL injection vector
(max_results flows in from a caller) and had no cap, so a tall
integer could drop unbounded rows on a production MySQL. The fix:
always LIMIT, clamp to [1, 1000], and bind as a parameter.
"""

from datetime import datetime

from flask import Flask
from sqlalchemy import func, select

from policyengine_api.data.v1_models import ReformImpact
from policyengine_api.routes.reform_impact_routes import reform_impact_bp


def _get_simulations(max_results=100):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(reform_impact_bp)
    query = "" if max_results is None else f"?max_results={max_results}"
    return app.test_client().get(f"/simulations{query}").get_json()


def _seed_reform_impacts(orm_session, n: int) -> None:
    for i in range(n):
        orm_session.add(
            ReformImpact(
                baseline_policy_id=i + 1,
                reform_policy_id=i + 2,
                country_id="us",
                region="us",
                dataset="custom_dataset",
                time_period="2025",
                options_json={},
                options_hash=f"hash-{i}",
                api_version="1.0.0",
                reform_impact_json={},
                status="complete",
                start_time=datetime(2026, 1, 1, 0, i // 60, i % 60),
                execution_id=f"exec-{i}",
            )
        )
    orm_session.commit()


def test_get_simulations_default_limit_caps_at_100(orm_session):
    _seed_reform_impacts(orm_session, 150)
    result = _get_simulations()
    assert len(result["result"]) == 100


def test_get_simulations_clamps_huge_max_results(orm_session):
    _seed_reform_impacts(orm_session, 50)
    # A caller passing an absurdly large value must not crash and
    # must not cause a full scan; the value is clamped at 1000.
    result = _get_simulations(max_results=10**9)
    assert len(result["result"]) == 50  # only 50 seeded


def test_get_simulations_clamps_negative_max_results(orm_session):
    _seed_reform_impacts(orm_session, 5)
    # max_results of 0 or negative must still return something sane.
    result = _get_simulations(max_results=0)
    assert 1 <= len(result["result"]) <= 5


def test_get_simulations_defaults_when_none(orm_session):
    _seed_reform_impacts(orm_session, 10)
    result = _get_simulations(max_results=None)
    assert len(result["result"]) == 10  # fewer than the default 100


def test_get_simulations_rejects_non_integer_gracefully(orm_session):
    _seed_reform_impacts(orm_session, 5)
    # A string like "100; DROP TABLE reform_impact" must not reach
    # the SQL statement; it falls back to the default.
    result = _get_simulations(max_results="100; DROP TABLE reform_impact")
    assert len(result["result"]) == 5

    # And the table must still exist.
    assert orm_session.scalar(select(func.count()).select_from(ReformImpact)) == 5
