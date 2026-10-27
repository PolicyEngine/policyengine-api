"""The reporting window: one US Eastern calendar day, and the week before it."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from datetime import time as time_of_day
from typing import NamedTuple
from zoneinfo import ZoneInfo

REPORTING_TIME_ZONE = ZoneInfo("America/New_York")
MIDNIGHT = time_of_day(0, 0)

# Each run also reads the seven days before the window, for comparison rates,
# first-seen times and regressions.
LOOKBACK = timedelta(days=7)


class ReportingWindow(NamedTuple):
    """One Eastern calendar day, as the half-open interval [start, end)."""

    start: datetime
    end: datetime

    @property
    def hours(self) -> float:
        """Return the elapsed hours: 23 or 25 on the days the clocks change."""
        return _hours_between(self.start, self.end)

    @property
    def lookback_start(self) -> datetime:
        """Return midnight Eastern seven days before the window starts."""
        return self.start - LOOKBACK

    @property
    def lookback_hours(self) -> float:
        """Return the elapsed hours of the seven days before the window."""
        return _hours_between(self.lookback_start, self.start)


def _hours_between(start: datetime, end: datetime) -> float:
    # Subtracting two datetimes in the same zone ignores a clock change, so
    # compare them in UTC.
    return (end.astimezone(UTC) - start.astimezone(UTC)) / timedelta(hours=1)


def reporting_window(report_date: date) -> ReportingWindow:
    """Return the window from midnight Eastern on ``report_date`` to the next."""
    next_date = report_date + timedelta(days=1)
    return ReportingWindow(
        start=datetime.combine(report_date, MIDNIGHT, tzinfo=REPORTING_TIME_ZONE),
        end=datetime.combine(next_date, MIDNIGHT, tzinfo=REPORTING_TIME_ZONE),
    )


def default_report_date(now: datetime) -> date:
    """Return the most recent Eastern calendar day that ended before ``now``."""
    return now.astimezone(REPORTING_TIME_ZONE).date() - timedelta(days=1)
