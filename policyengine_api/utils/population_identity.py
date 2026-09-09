"""Shared identity rules for legacy simulation population references."""

from sqlalchemy import LargeBinary, and_, cast
from sqlalchemy.sql import ColumnElement, SQLColumnExpression


def canonical_numeric_household_id(
    country_id: str, population_id: str | int, population_type: str
) -> str | None:
    """Resolve only US household references made entirely of ASCII decimal digits.

    The returned value is for comparison and new records. Saved simulation IDs
    and report input snapshots retain their original spelling.
    """
    value = str(population_id)
    if (
        country_id == "us"
        and population_type == "household"
        and value.isascii()
        and value.isdecimal()
    ):
        return value.lstrip("0") or "0"
    return None


def population_id_matches(
    column: SQLColumnExpression[str],
    country_id: str,
    population_id: str | int,
    population_type: str,
) -> ColumnElement[bool]:
    """Match US numeric aliases without integer casts or collation equivalence."""
    if country_id != "us" or population_type != "household":
        return column == population_id
    numeric_id = canonical_numeric_household_id(
        country_id, population_id, population_type
    )
    if numeric_id is None:
        # MySQL text equality can ignore trailing spaces or equate Unicode
        # characters. Opaque IDs must match their bytes, not a numeric alias.
        return cast(column, LargeBinary) == str(population_id).encode("utf-8")
    # '$' can match before a final newline. The second condition guarantees
    # every character is an ASCII digit, including under MySQL regex rules.
    return and_(
        column.regexp_match(f"^0*{numeric_id}$"),
        ~column.regexp_match("[^0-9]"),
    )
