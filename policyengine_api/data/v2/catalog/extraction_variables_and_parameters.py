"""Normalize a public model's variables, parameters and parameter nodes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from policyengine_api.data.v2.catalog.extraction_values import (
    CatalogExtractionError,
    catalog_identifier,
    normalize_json_value,
    optional_text,
    required_text,
)
from policyengine_api.data.v2.catalog.records import (
    ParameterNodeRecord,
    ParameterRecord,
    ParameterValueRecord,
    VariableRecord,
)

if TYPE_CHECKING:
    from uuid import UUID


def _type_name(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    name = getattr(value, "__name__", None)
    if not isinstance(name, str) or not name:
        msg = f"unsupported data type {value!r}"
        raise CatalogExtractionError(msg)
    return name


def _aware_datetime(value: object, *, field_name: str) -> datetime:
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime(value.year, value.month, value.day, tzinfo=UTC)
    if not isinstance(value, datetime):
        msg = f"{field_name} must be a date or datetime"
        raise CatalogExtractionError(msg)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _optional_aware_datetime(value: object, *, field_name: str) -> datetime | None:
    if value is None:
        return None
    return _aware_datetime(value, field_name=field_name)


def normalize_variable(
    source: object,
    *,
    model_version_id: UUID,
) -> VariableRecord:
    """Normalize one public variable into its catalog record."""
    name = required_text(
        getattr(source, "name", None), field_name="variable name", maximum=512
    )
    possible_values = getattr(source, "possible_values", None)
    if possible_values is not None:
        if not isinstance(possible_values, Sequence) or isinstance(
            possible_values, (str, bytes)
        ):
            msg = f"variable {name!r} possible_values must be a sequence"
            raise CatalogExtractionError(msg)
        normalized_possible_values = [
            required_text(
                value, field_name=f"variable {name} possible value", maximum=255
            )
            for value in possible_values
        ]
    else:
        normalized_possible_values = None

    def optional_names(attribute: str) -> list[str] | None:
        values = getattr(source, attribute, None)
        if values is None:
            return None
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            msg = f"variable {name!r} {attribute} must be a sequence"
            raise CatalogExtractionError(msg)
        return [
            required_text(
                value,
                field_name=f"variable {name} {attribute} item",
                maximum=512,
            )
            for value in values
        ]

    return VariableRecord(
        id=catalog_identifier("variable", model_version_id, name),
        model_version_id=model_version_id,
        name=name,
        label=optional_text(
            getattr(source, "label", None),
            field_name=f"variable {name} label",
            maximum=512,
        ),
        entity=required_text(
            getattr(source, "entity", None),
            field_name=f"variable {name} entity",
            maximum=128,
        ),
        description=optional_text(
            getattr(source, "description", None),
            field_name=f"variable {name} description",
        ),
        data_type=_type_name(getattr(source, "data_type", None)),
        possible_values=normalized_possible_values,
        default_value=normalize_json_value(getattr(source, "default_value", None)),
        adds=optional_names("adds"),
        subtracts=optional_names("subtracts"),
    )


def normalize_parameter(
    source: object,
    *,
    model_version_id: UUID,
) -> ParameterRecord:
    """Normalize one public parameter and its ordered, canonical values."""
    name = required_text(
        getattr(source, "name", None),
        field_name="parameter name",
        maximum=512,
    )
    parameter_id = catalog_identifier("parameter", model_version_id, name)
    source_values: list[tuple[datetime, datetime | None, Any]] = []
    values_by_start: dict[datetime, tuple[datetime | None, Any]] = {}
    previous_start: datetime | None = None
    for source_value in getattr(source, "parameter_values", ()):
        start_date = _aware_datetime(
            getattr(source_value, "start_date", None),
            field_name=f"parameter {name} value start_date",
        )
        end_date = _optional_aware_datetime(
            getattr(source_value, "end_date", None),
            field_name=f"parameter {name} value end_date",
        )
        try:
            value_json = normalize_json_value(getattr(source_value, "value", None))
        except CatalogExtractionError as error:
            msg = f"parameter {name!r} has an unsupported JSON value: {error}"
            raise CatalogExtractionError(msg) from error
        if start_date in values_by_start:
            previous_end, previous_value = values_by_start[start_date]
            if previous_value != value_json:
                msg = (
                    f"parameter {name!r} has conflicting values at effective "
                    f"date {start_date.isoformat()}"
                )
                raise CatalogExtractionError(msg)
            if previous_end != end_date:
                msg = (
                    f"parameter {name!r} exposes inconsistent intervals at effective "
                    f"date {start_date.isoformat()}"
                )
                raise CatalogExtractionError(msg)
            continue
        if previous_start is not None and start_date <= previous_start:
            msg = f"parameter {name!r} values are not ordered oldest to newest"
            raise CatalogExtractionError(msg)
        values_by_start[start_date] = (end_date, value_json)
        previous_start = start_date
        source_values.append((start_date, end_date, value_json))

    normalized_values: list[ParameterValueRecord] = []
    for index, (start_date, supplied_end, value_json) in enumerate(source_values):
        expected_end = (
            source_values[index + 1][0] - timedelta(days=1)
            if index + 1 < len(source_values)
            else None
        )
        if supplied_end != expected_end:
            msg = f"parameter {name!r} does not expose canonical inclusive intervals"
            raise CatalogExtractionError(msg)
        normalized_values.append(
            ParameterValueRecord(
                id=catalog_identifier(
                    "parameter-value", parameter_id, start_date.isoformat()
                ),
                parameter_id=parameter_id,
                value_json=value_json,
                start_date=start_date,
                end_date=expected_end,
            )
        )

    return ParameterRecord(
        id=parameter_id,
        model_version_id=model_version_id,
        name=name,
        label=optional_text(
            getattr(source, "label", None),
            field_name=f"parameter {name} label",
            maximum=512,
        ),
        description=optional_text(
            getattr(source, "description", None),
            field_name=f"parameter {name} description",
        ),
        data_type=_type_name(getattr(source, "data_type", None)),
        unit=optional_text(
            getattr(source, "unit", None),
            field_name=f"parameter {name} unit",
            maximum=128,
        ),
        values=tuple(normalized_values),
    )


def public_named_records(
    source: object,
    *,
    attribute: str,
    entity_name: str,
) -> tuple[object, ...]:
    """Return a name-indexed mapping's records in name order, keyed by name."""
    records = getattr(source, attribute, None)
    if not isinstance(records, Mapping):
        msg = f"public model {attribute} must be a name-indexed mapping"
        raise CatalogExtractionError(msg)

    normalized: list[object] = []
    for key, record in sorted(records.items()):
        name = getattr(record, "name", None)
        if key != name:
            msg = (
                f"{entity_name} mapping key {key!r} does not match record name {name!r}"
            )
            raise CatalogExtractionError(msg)
        normalized.append(record)
    return tuple(normalized)


def normalize_parameter_nodes(
    source: object,
    *,
    model_version_id: UUID,
) -> tuple[ParameterNodeRecord, ...]:
    """Normalize the public model's named parameter nodes, in name order."""
    normalized_nodes: list[ParameterNodeRecord] = []
    for node in public_named_records(
        source,
        attribute="parameter_nodes_by_name",
        entity_name="parameter node",
    ):
        source_name = getattr(node, "name", None)
        # The public UK model includes one unnamed structural root. It has no
        # addressable identity and contains no metadata of its own.
        if source_name == "":
            continue
        node_name = required_text(
            source_name,
            field_name="parameter node name",
            maximum=512,
        )
        normalized_nodes.append(
            ParameterNodeRecord(
                id=catalog_identifier("parameter-node", model_version_id, node_name),
                model_version_id=model_version_id,
                name=node_name,
                label=optional_text(
                    getattr(node, "label", None),
                    field_name="parameter node label",
                    maximum=512,
                ),
                description=optional_text(
                    getattr(node, "description", None),
                    field_name="parameter node description",
                ),
            )
        )
    return tuple(normalized_nodes)
