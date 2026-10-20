"""Report each day's telemetry error groups as GitHub issues.

Each run reads one US Eastern calendar day of error records from the central
Cloud Logging bucket through its linked BigQuery dataset. It groups the records
by a keyed fingerprint, measures each group in production and staging, and
creates or updates one GitHub issue per production error group.

Workflow logs, job summaries and issues in this repository are public. The
script therefore publishes only fingerprints, counts, code-defined names and a
Logs Explorer link, never error messages, stack text or identifiers.
"""

from __future__ import annotations

import argparse
import re
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, NamedTuple
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from collections.abc import Iterable

REPORTING_TIME_ZONE = ZoneInfo("America/New_York")

# Shown in place of a value that is missing, or that fails validation and so
# might not be code-defined.
MISSING = "-"
UNRECOGNIZED = "<unrecognized>"

PRODUCTION_ENVIRONMENT_NAMES = frozenset({"production", "main"})
STAGING_ENVIRONMENT_NAMES = frozenset({"staging"})
VERSIONED_SIMULATION_SERVICE = re.compile(r"^(policyengine-simulation-py)\d+-\d+-\d+$")

# Captures 'path", line N, in function' from each frame header of a Python
# traceback, including indented and "|"-prefixed exception group frames. It has
# one capturing group because BigQuery's REGEXP_EXTRACT_ALL allows only one,
# and the trailing newline skips a header that stack truncation cut short.
FRAME_PATTERN = r'File "([^"\n]+", line [0-9]+, in [^\s]+)\n'
FRAME_PARTS = re.compile(r'^(?P<path>[^"\n]+)", line [0-9]+, in (?P<function>\S+)$')
FINGERPRINT_FRAME_COUNT = 3
INSTALLED_PACKAGE_PREFIX = re.compile(r"^.*/(?:site|dist)-packages/")
STANDARD_LIBRARY_PREFIX = re.compile(r"^.*/lib/python3(?:\.\d+)?/")
APPLICATION_PACKAGES = (
    r"(?:policyengine_api|policyengine_fastapi"
    r"|policyengine_simulation_[a-z0-9_]+|policyengine_stage12_[a-z0-9_]+)/"
)
APPLICATION_PATH = re.compile(rf"^{APPLICATION_PACKAGES}")
APPLICATION_PATH_IN_ABSOLUTE_PATH = re.compile(rf"(?:^|/)({APPLICATION_PACKAGES}.*)$")
FALLBACK_PATH_COMPONENTS = 2

ERROR_TYPE_PATTERN = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$", re.ASCII)
MAX_ERROR_TYPE_LENGTH = 120
UNMATCHED_ROUTE = "<unmatched>"
MAX_ROUTE_LENGTH = 200
ROUTE_PARAMETER = re.compile(
    r"^(?:<(?:[a-z]+:)?[A-Za-z_]\w*>|\{[A-Za-z_]\w*(?::[a-z]+)?\})$", re.ASCII
)
ROUTE_LITERAL = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,39}$")
# Literal route segments are words such as "v2" or "user-policies". A segment
# with more digits than this is more likely a record ID than code.
MAX_ROUTE_LITERAL_DIGITS = 2
FAMILY_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
MAX_FAMILY_LENGTH = 63
OPERATION_PATTERN = re.compile(r"^[A-Za-z_][\w.:/-]*$", re.ASCII)
MAX_OPERATION_LENGTH = 100
LOWEST_HTTP_STATUS = 100
HIGHEST_HTTP_STATUS = 599


class ReportingWindow(NamedTuple):
    """One Eastern calendar day, as the half-open interval [start, end)."""

    start: datetime
    end: datetime

    @property
    def hours(self) -> float:
        """Return the elapsed hours: 23 or 25 on the days the clocks change."""
        elapsed = self.end.astimezone(UTC) - self.start.astimezone(UTC)
        return elapsed / timedelta(hours=1)


def reporting_window(report_date: date) -> ReportingWindow:
    """Return the window from midnight Eastern on ``report_date`` to the next."""
    next_date = report_date + timedelta(days=1)
    return ReportingWindow(
        start=datetime.combine(report_date, time(0), tzinfo=REPORTING_TIME_ZONE),
        end=datetime.combine(next_date, time(0), tzinfo=REPORTING_TIME_ZONE),
    )


def default_report_date(now: datetime) -> date:
    """Return the most recent Eastern calendar day that ended before ``now``."""
    return now.astimezone(REPORTING_TIME_ZONE).date() - timedelta(days=1)


def service_family(service_name: str) -> str:
    """Return the service name, merging versioned simulation services into one."""
    return VERSIONED_SIMULATION_SERVICE.sub(r"\1", service_name)


def environment_class(environment_name: str | None) -> str:
    """Classify a deployment environment name as production, staging or other.

    The Modal gateway reports its production environment as ``main``.
    """
    if environment_name in PRODUCTION_ENVIRONMENT_NAMES:
        return "production"
    if environment_name in STAGING_ENVIRONMENT_NAMES:
        return "staging"
    return "other"


def normalize_path(path: str) -> str:
    """Return a source path without its installation or checkout prefix."""
    installed = INSTALLED_PACKAGE_PREFIX.sub("", path, count=1)
    if installed != path:
        return installed
    application = APPLICATION_PATH_IN_ABSOLUTE_PATH.search(path)
    if application:
        return application.group(1)
    standard_library = STANDARD_LIBRARY_PREFIX.sub("", path, count=1)
    if standard_library != path:
        return standard_library
    return "/".join(path.split("/")[-FALLBACK_PATH_COMPONENTS:])


def frame_key(frame: str) -> str | None:
    """Return ``path:function`` for one ``FRAME_PATTERN`` match, without its line."""
    parts = FRAME_PARTS.match(frame)
    if parts is None:
        return None
    return f"{normalize_path(parts['path'])}:{parts['function']}"


def fingerprint_frames(frames: Iterable[str] | None) -> tuple[str, ...]:
    """Choose the frames that identify where an exception was raised.

    These are the three innermost frames in application packages. Without
    application frames they are the three innermost frames of any kind, and
    without a stack, a placeholder.
    """
    keys = [key for key in map(frame_key, frames or ()) if key is not None]
    if not keys:
        return (MISSING,)
    application_keys = [key for key in keys if APPLICATION_PATH.match(key)]
    return tuple((application_keys or keys)[-FINGERPRINT_FRAME_COUNT:])


def _validated(value: str | None, pattern: re.Pattern[str], max_length: int) -> str:
    if not value:
        return MISSING
    if len(value) <= max_length and pattern.fullmatch(value):
        return value
    return UNRECOGNIZED


def public_error_type(value: str | None) -> str:
    """Return an exception class name, or a placeholder for anything else."""
    return _validated(value, ERROR_TYPE_PATTERN, MAX_ERROR_TYPE_LENGTH)


def public_family(value: str | None) -> str:
    """Return a service name or family, or a placeholder for anything else."""
    return _validated(value, FAMILY_PATTERN, MAX_FAMILY_LENGTH)


def public_operation(value: str | None) -> str:
    """Return a code-defined operation name, or a placeholder for anything else."""
    return _validated(value, OPERATION_PATTERN, MAX_OPERATION_LENGTH)


def _route_segment_is_code(segment: str) -> bool:
    if ROUTE_PARAMETER.match(segment):
        return True
    digits = sum(character.isdigit() for character in segment)
    return bool(ROUTE_LITERAL.match(segment)) and digits <= MAX_ROUTE_LITERAL_DIGITS


def public_route(value: str | None) -> str:
    """Return a route template, or a placeholder for anything else.

    A path that holds a record ID, a query string or free text is not a
    template, so it never reaches public output.
    """
    if not value:
        return MISSING
    if value == UNMATCHED_ROUTE:
        return value
    if len(value) > MAX_ROUTE_LENGTH or not value.startswith("/"):
        return UNRECOGNIZED
    segments = [segment for segment in value.split("/") if segment]
    if all(map(_route_segment_is_code, segments)):
        return value
    return UNRECOGNIZED


def public_status(value: object) -> int | None:
    """Return an HTTP status code as an integer, or None for anything else."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.isascii() and value.isdigit():
        value = int(value)
    if isinstance(value, int) and LOWEST_HTTP_STATUS <= value <= HIGHEST_HTTP_STATUS:
        return value
    return None


def _report_date_argument(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        msg = "expected an Eastern calendar date as YYYY-MM-DD"
        raise argparse.ArgumentTypeError(msg) from error


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the command line; argparse exits with code 2 on invalid input."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--project-id",
        required=True,
        help="Google Cloud project that holds the linked BigQuery dataset",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="query and group errors, but make no changes to GitHub issues",
    )
    parser.add_argument(
        "--report-date",
        type=_report_date_argument,
        default=None,
        help="Eastern calendar day to report (default: the previous day)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run one report and return the process exit code."""
    parse_arguments(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
