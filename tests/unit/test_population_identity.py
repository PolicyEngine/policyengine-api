"""Numeric household identity must not inherit permissive text equality."""

import pytest
from sqlalchemy import literal, select

from policyengine_api.utils.population_identity import population_id_matches


@pytest.mark.parametrize(
    "stored,requested,expected",
    [
        ("1 ", "1", False),
        ("1", "1 ", False),
        ("1 ", "1 ", True),
        ("00001", "1", True),
        ("1\n", "1", False),
        ("１", "1", False),
        ("1", "１", False),
    ],
)
def test_sql_alias_matching_is_strict_even_with_permissive_text_collation(
    orm_session, stored, requested, expected
):
    # SQLite's RTRIM gives a real permissive-equality control without claiming
    # MySQL qualification or depending on that independently owned database.
    assert orm_session.scalar(select(literal("1 ").collate("RTRIM") == "1")) is True
    matches = population_id_matches(
        literal(stored).collate("RTRIM"), "us", requested, "household"
    )
    assert orm_session.scalar(select(matches)) is expected
