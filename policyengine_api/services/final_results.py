"""The rule that a complete v1 simulation or report result is final.

Simulation and report records are shared: identical requests reuse one record,
and anyone can update one by its ID. So once a record holds a complete result,
an update may only repeat it (a retried write, or a second browser finishing
the same calculation) and never change it.
"""

import json
from collections.abc import Mapping


def _comparable_output(value: object) -> object:
    """Return stored output as JSON data, decoding a legacy JSON-string value."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def changes_stored_result(record: object, values: Mapping[str, object]) -> bool:
    """Whether applying ``values`` would change any of those fields on ``record``."""
    for field, value in values.items():
        stored = getattr(record, field)
        if field == "output":
            stored = _comparable_output(stored)
        if stored != value:
            return True
    return False
