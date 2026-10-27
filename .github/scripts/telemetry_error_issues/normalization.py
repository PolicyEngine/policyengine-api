"""Normalize service, environment and source names, and validate public values.

Each ``public_*`` function returns a value only if it matches the pattern of a
code-defined name, and a placeholder otherwise, so that free text from a record
never reaches an issue, a log or a job summary.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Iterable

# Shown in place of a value that is missing, or that fails validation and so
# might not be code-defined.
MISSING = "-"
UNRECOGNIZED = "<unrecognized>"

PRODUCTION_ENVIRONMENT_NAMES = frozenset({"production", "main"})
STAGING_ENVIRONMENT_NAMES = frozenset({"staging"})
VERSIONED_SIMULATION_SERVICE = re.compile(r"^(policyengine-simulation-py)\d+-\d+-\d+$")

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


class FrameLocation(NamedTuple):
    """The source file and function of one stack frame."""

    path: str
    function: str


def frame_location(frame: str) -> FrameLocation | None:
    """Return the normalized path and the function of one ``FRAME_PATTERN`` match.

    The frame's line number is dropped.
    """
    parts = FRAME_PARTS.match(frame)
    if parts is None:
        return None
    return FrameLocation(normalize_path(parts["path"]), parts["function"])


def function_key(function: str) -> str:
    """Return a function name without its leading underscores."""
    return function.lstrip("_")


def fingerprint_frames(frames: Iterable[str] | None) -> tuple[str, ...]:
    """Choose the frames that identify where an exception was raised, and key them.

    ``frames`` come from the first traceback of the stack only (see
    ``CHAINED_EXCEPTION_PATTERN``); for a chained exception that is its first
    cause. These are the three innermost frames whose paths are in
    application packages. Without application frames they are the three
    innermost frames of any kind, and without a stack, a placeholder.

    Each chosen frame is keyed by its function name alone, without leading
    underscores, so moving a function to another module, or making a private
    helper public, keeps the fingerprint. Any other rename changes it.
    """
    locations = [
        location
        for location in map(frame_location, frames or ())
        if location is not None
    ]
    if not locations:
        return (MISSING,)
    application_locations = [
        location for location in locations if APPLICATION_PATH.match(location.path)
    ]
    chosen = (application_locations or locations)[-FINGERPRINT_FRAME_COUNT:]
    return tuple(function_key(location.function) for location in chosen)


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


def is_route_template(value: str | None) -> bool:
    """Return whether ``value`` is a route template rather than a placeholder.

    The placeholders are the missing and unrecognized values ``public_route``
    shows, and ``<unmatched>``, which a service logs as the route of a
    request that matched none of its routes.
    """
    return public_route(value) not in {MISSING, UNRECOGNIZED, UNMATCHED_ROUTE}


def public_status(value: object) -> int | None:
    """Return an HTTP status code as an integer, or None for anything else."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.isascii() and value.isdigit():
        value = int(value)
    if isinstance(value, int) and LOWEST_HTTP_STATUS <= value <= HIGHEST_HTTP_STATUS:
        return value
    return None
