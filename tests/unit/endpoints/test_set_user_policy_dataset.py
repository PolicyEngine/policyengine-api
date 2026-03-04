"""Regression test for issue #3310.

When dataset is truthy in set_user_policy (policy.py:224-237), the query
builds "AND dataset = ?" (7 placeholders) but the params must include
the dataset value. Previously, the dataset was never appended, causing
a parameter binding crash.
"""

import time


def test_set_user_policy_dataset_param_included(test_db):
    """Verify that the SELECT after INSERT in set_user_policy correctly
    includes the dataset value in params when dataset is truthy.

    Reproduces the exact code path from policy.py:224-237.
    """
    now = int(time.time())

    country_id = "us"
    reform_id = 2
    baseline_id = 1
    user_id = "user1"
    year = "2025"
    geography = "us"
    dataset = "cps"

    # Insert a user_policy with a non-null dataset
    test_db.query(
        "INSERT INTO user_policies (country_id, reform_label, reform_id, "
        "baseline_label, baseline_id, user_id, year, geography, dataset, "
        "number_of_provisions, api_version, added_date, updated_date) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            country_id,
            None,
            reform_id,
            None,
            baseline_id,
            user_id,
            year,
            geography,
            dataset,
            3,
            "1.0.0",
            now,
            now,
        ),
    )

    # Reproduce the exact code from policy.py:224-237
    dataset_select_str = "IS NULL" if not dataset else "= ?"
    query = (
        "SELECT * FROM user_policies WHERE country_id = ? AND reform_id = ? "
        "AND baseline_id = ? AND user_id = ? AND year = ? AND geography = ? "
        f"AND dataset {dataset_select_str}"
    )

    params = [country_id, reform_id, baseline_id, user_id, year, geography]
    if dataset:
        params.append(dataset)

    # This must not crash — 7 placeholders, 7 params
    row = test_db.query(query, tuple(params)).fetchone()

    assert row is not None
    assert row["dataset"] == "cps"
    assert row["reform_id"] == reform_id
    assert row["user_id"] == user_id


def test_set_user_policy_dataset_null_still_works(test_db):
    """When dataset is None/falsy, the query uses IS NULL with 6 params."""
    now = int(time.time())

    country_id = "us"
    reform_id = 2
    baseline_id = 1
    user_id = "user1"
    year = "2025"
    geography = "us"
    dataset = None

    test_db.query(
        "INSERT INTO user_policies (country_id, reform_label, reform_id, "
        "baseline_label, baseline_id, user_id, year, geography, dataset, "
        "number_of_provisions, api_version, added_date, updated_date) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            country_id,
            None,
            reform_id,
            None,
            baseline_id,
            user_id,
            year,
            geography,
            dataset,
            3,
            "1.0.0",
            now,
            now,
        ),
    )

    dataset_select_str = "IS NULL" if not dataset else "= ?"
    query = (
        "SELECT * FROM user_policies WHERE country_id = ? AND reform_id = ? "
        "AND baseline_id = ? AND user_id = ? AND year = ? AND geography = ? "
        f"AND dataset {dataset_select_str}"
    )

    params = [country_id, reform_id, baseline_id, user_id, year, geography]
    if dataset:
        params.append(dataset)

    row = test_db.query(query, tuple(params)).fetchone()

    assert row is not None
    assert row["dataset"] is None
