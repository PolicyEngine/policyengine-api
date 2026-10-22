"""Checks of the stored countries rows against the country list in code."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable


class CountryListMismatchError(RuntimeError):
    """The countries table and the country list in code name different countries.

    ``listed_without_row`` holds the listed countries that have no row, and
    ``rows_not_listed`` the rows for countries the list does not name, each
    sorted by ID.
    """

    def __init__(
        self,
        *,
        listed_without_row: tuple[str, ...],
        rows_not_listed: tuple[str, ...],
    ) -> None:
        """Record both differences and describe them in the message."""
        self.listed_without_row = listed_without_row
        self.rows_not_listed = rows_not_listed
        super().__init__(
            "the countries table does not match the country list in code: "
            f"listed without a row: {', '.join(listed_without_row) or 'none'}; "
            f"rows not listed: {', '.join(rows_not_listed) or 'none'}"
        )


def validate_countries_match_code_list(
    *,
    stored_country_ids: Iterable[str],
    listed_country_ids: Iterable[str],
) -> None:
    """Raise ``CountryListMismatchError`` unless both name the same countries."""
    stored = set(stored_country_ids)
    listed = set(listed_country_ids)
    if stored == listed:
        return
    raise CountryListMismatchError(
        listed_without_row=tuple(sorted(listed - stored)),
        rows_not_listed=tuple(sorted(stored - listed)),
    )
