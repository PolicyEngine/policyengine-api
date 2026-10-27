"""Where the central telemetry logs are, as the deployment's settings name them.

The names come from repository variables. BigQuery can't take a dataset or a
table name as a query parameter, so each name must match a strict identifier
pattern when the settings are read, and again just before it goes into a
query, a job configuration or a Logs Explorer link. A name that doesn't match
is refused, which keeps SQL out of the query.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# Each pattern allows only ASCII letters, digits and the separators the
# resource's own naming rules allow, and only within their length limits.
PROJECT_ID_PATTERN = re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]")
LOG_BUCKET_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}")
LOCATION_PATTERN = re.compile(r"[a-z][a-z0-9-]{0,62}")
DATASET_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,1023}")
# Cloud Logging gives a linked dataset's view the name of the log view.
LOG_VIEW_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,99}")


class LogSource(NamedTuple):
    """The project, log bucket, linked dataset and view the run reads.

    ``service_namespace`` selects the application's records. It reaches BigQuery
    only as a query parameter, so it needs no identifier pattern.
    """

    project_id: str
    bucket: str
    bucket_location: str
    dataset: str
    view: str
    service_namespace: str


def checked_identifier(value: str, pattern: re.Pattern[str], setting: str) -> str:
    """Return ``value`` if all of it matches ``pattern``, else raise ValueError.

    The error names the setting, never the value, because a value that fails
    the check might be anything.
    """
    if pattern.fullmatch(value) is None:
        msg = f"{setting} is not a valid name"
        raise ValueError(msg)
    return value
