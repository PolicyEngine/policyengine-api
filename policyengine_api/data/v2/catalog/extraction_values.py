"""Catalog extraction errors, record identifiers, and text and JSON value checks."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from datetime import date, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, UUID, uuid5

if TYPE_CHECKING:
    from policyengine_api.json_types import JSONValue


class CatalogExtractionError(RuntimeError):
    """Raised before database access when source metadata cannot be normalized."""


def catalog_identifier(*parts: object) -> UUID:
    """Return the catalog's deterministic UUID for the record named by ``parts``."""
    value = "/".join(str(part) for part in parts)
    return uuid5(NAMESPACE_URL, f"https://api.policyengine.org/v2/catalog/{value}")


def required_text(value: object, *, field_name: str, maximum: int) -> str:
    """Return stripped text; raise unless it is non-empty and within ``maximum``."""
    if not isinstance(value, str) or not value.strip():
        msg = f"{field_name} must be a non-empty string"
        raise CatalogExtractionError(msg)
    normalized = value.strip()
    if len(normalized) > maximum:
        msg = f"{field_name} exceeds {maximum} characters"
        raise CatalogExtractionError(msg)
    return normalized


def optional_text(
    value: object,
    *,
    field_name: str,
    maximum: int | None = None,
) -> str | None:
    """Return ``value`` if it is None or text within ``maximum``; raise otherwise."""
    if value is None:
        return None
    if not isinstance(value, str):
        msg = f"{field_name} must be a string or null"
        raise CatalogExtractionError(msg)
    if maximum is not None and len(value) > maximum:
        msg = f"{field_name} exceeds {maximum} characters"
        raise CatalogExtractionError(msg)
    return value


def _normalize_json_float(value: float) -> JSONValue:
    """Keep a finite float, write an infinity as a string and reject NaN."""
    if math.isnan(value):
        msg = "NaN is not JSON-compatible"
        raise CatalogExtractionError(msg)
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    return value


def _normalize_json_enum(value: Enum) -> JSONValue:
    """Normalize an enum member's value."""
    return normalize_json_value(value.value)


def _normalize_json_date(value: date) -> JSONValue:
    """Write a date or datetime in ISO 8601 form."""
    return value.isoformat()


def _normalize_json_object(value: Mapping[object, object]) -> JSONValue:
    """Normalize a mapping's values, requiring string keys."""
    normalized: dict[str, JSONValue] = {}
    for key, nested in value.items():
        if not isinstance(key, str):
            msg = "JSON object keys must be strings"
            raise CatalogExtractionError(msg)
        normalized[key] = normalize_json_value(nested)
    return normalized


def _normalize_json_array(value: list[object] | tuple[object, ...]) -> JSONValue:
    """Normalize each item of a list or tuple into a JSON array."""
    return [normalize_json_value(item) for item in value]


# Checked in order, so an enum or date that is also a container or number is
# normalized as the enum or date it is.
JSON_VALUE_NORMALIZERS: tuple[
    tuple[type | tuple[type, ...], Callable[[Any], JSONValue]], ...
] = (
    (float, _normalize_json_float),
    (Enum, _normalize_json_enum),
    ((date, datetime), _normalize_json_date),
    (Mapping, _normalize_json_object),
    ((list, tuple), _normalize_json_array),
)


def _normalize_json_scalar(value: object) -> JSONValue:
    """Unwrap a NumPy-style scalar through its ``item()``, or reject the value."""
    item = getattr(value, "item", None)
    if callable(item):
        scalar = item()
        if scalar is not value:
            return normalize_json_value(scalar)
    msg = f"unsupported JSON value type {type(value).__module__}.{type(value).__name__}"
    raise CatalogExtractionError(msg)


def normalize_json_value(value: object) -> JSONValue:
    """Convert supported public values into strict JSON-compatible values."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    for value_types, normalize in JSON_VALUE_NORMALIZERS:
        if isinstance(value, value_types):
            return normalize(value)
    return _normalize_json_scalar(value)
