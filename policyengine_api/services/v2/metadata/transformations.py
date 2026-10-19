"""Pure representation transformations for v2 metadata operations."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TypeVar

from policyengine_api.dataset_display import get_dataset_display_label
from policyengine_api.services.v2.metadata.types import (
    MetadataCanonicalParameterValue,
    MetadataCatalogDocument,
    MetadataDataset,
    MetadataDatasetOption,
    MetadataEconomyOptionsResult,
    MetadataEntity,
    MetadataModel,
    MetadataModelSelectionResult,
    MetadataModelVersionDetail,
    MetadataPageResult,
    MetadataParameterChild,
    MetadataParameterSummary,
    MetadataRegion,
    MetadataRegionOption,
    MetadataRegionType,
    MetadataTimePeriodOption,
    MetadataVariable,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from uuid import UUID

    from policyengine_api.data.v2.catalog.catalog_selection import SelectedCatalog
    from policyengine_api.data.v2.models import (
        Dataset,
        Parameter,
        ParameterNode,
        ParameterValue,
        Region,
        Variable,
    )
    from policyengine_api.services.v2.metadata.types import (
        MetadataCatalogParameterRow,
    )

ResourceT = TypeVar("ResourceT")


def page_result(
    selected: SelectedCatalog,
    rows: list[ResourceT],
    *,
    offset: int,
    limit: int,
) -> MetadataPageResult[ResourceT]:
    """Wrap fetched rows as one page of the selected catalog.

    rows holds up to limit + 1 items; an extra item only sets has_more and is
    dropped from the page.
    """
    return MetadataPageResult(
        policyengine_version=selected.policyengine_version,
        items=rows[:limit],
        offset=offset,
        limit=limit,
        has_more=len(rows) > limit,
    )


def metadata_model(selected: SelectedCatalog) -> MetadataModel:
    """Describe the catalog's model, using the selected version's description."""
    return MetadataModel(
        id=selected.model.id,
        name=selected.model.name,
        description=selected.model_version.description,
    )


def metadata_model_version(selected: SelectedCatalog) -> MetadataModelVersionDetail:
    """Describe the selected model version, with its current-law id and years."""
    return MetadataModelVersionDetail(
        id=selected.model_version.id,
        model_id=selected.model.id,
        version=selected.model_version.version,
        description=selected.model_version.description,
        current_law_id=selected.model_version.current_law_id,
        metadata_time_periods=selected.model_version.metadata_time_periods,
        catalog_format=selected.model_version.catalog_format,
        entities=(
            None
            if selected.model_version.entities is None
            else [
                MetadataEntity.model_validate(entity)
                for entity in selected.model_version.entities
            ]
        ),
        basic_inputs=selected.model_version.basic_inputs,
    )


def metadata_model_selection(selected: SelectedCatalog) -> MetadataModelSelectionResult:
    """Pair the catalog's model with its selected version."""
    return MetadataModelSelectionResult(
        policyengine_version=selected.policyengine_version,
        model=metadata_model(selected),
        model_version=metadata_model_version(selected),
    )


def metadata_variable(variable: Variable) -> MetadataVariable:
    """Return the API representation of a stored variable."""
    return MetadataVariable(
        id=variable.id,
        name=variable.name,
        label=variable.label,
        entity=variable.entity,
        description=variable.description,
        data_type=variable.data_type,
        possible_values=variable.possible_values,
        default_value=variable.default_value,
        adds=variable.adds,
        subtracts=variable.subtracts,
        value_type=variable.value_type,
        definition_period=variable.definition_period,
        unit=variable.unit,
        module_name=variable.module_name,
        is_input_variable=variable.is_input_variable,
        hidden_input=variable.hidden_input,
        possible_value_labels=variable.possible_value_labels,
    )


def metadata_parameter(parameter: Parameter) -> MetadataParameterSummary:
    """Return the API representation of a stored parameter."""
    return MetadataParameterSummary(
        id=parameter.id,
        name=parameter.name,
        label=parameter.label,
        description=parameter.description,
        data_type=parameter.data_type,
        unit=parameter.unit,
        metadata_label=parameter.metadata_label,
        period=parameter.period,
        economy=parameter.economy,
        household=parameter.household,
    )


def metadata_parameter_value(value: ParameterValue) -> MetadataCanonicalParameterValue:
    """Return the API representation of a stored value, exposing value_json as value."""
    return MetadataCanonicalParameterValue(
        id=value.id,
        parameter_id=value.parameter_id,
        value=value.value_json,
        start_date=value.start_date,
        end_date=value.end_date,
    )


def utc_day_start(selected_time: datetime) -> datetime:
    """Return midnight UTC on the day of selected_time, treating a naive time as UTC."""
    if selected_time.tzinfo is None:
        selected_time = selected_time.replace(tzinfo=UTC)
    return selected_time.astimezone(UTC).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def metadata_dataset(dataset: Dataset) -> MetadataDataset:
    """Return the API representation of a stored logical input dataset."""
    return MetadataDataset(
        id=dataset.id,
        name=dataset.name,
        description=dataset.description,
        year=dataset.year,
    )


def metadata_region(region: Region) -> MetadataRegion:
    """Return the API representation of a stored region."""
    return MetadataRegion(
        id=region.id,
        code=region.code,
        label=region.label,
        region_type=MetadataRegionType(region.region_type.value),
        requires_filter=region.requires_filter,
        filter_field=region.filter_field,
        filter_value=region.filter_value,
        filter_strategy=region.filter_strategy,
        parent_code=region.parent_code,
        state_code=region.state_code,
        state_name=region.state_name,
        default_dataset_id=region.default_dataset_id,
    )


def metadata_parameter_children(rows: list[Any]) -> list[MetadataParameterChild]:
    """Build parameter-tree children from read_parameter_children rows.

    Parameter leaves carry the parameter's summary, and a child with no label is
    labelled with the last segment of its path.
    """
    items = []
    for row in rows:
        parameter = None
        if row.type == "parameter":
            parameter = MetadataParameterSummary(
                id=row.parameter_id,
                name=row.path,
                label=row.parameter_label,
                description=row.parameter_description,
                data_type=row.parameter_data_type,
                unit=row.parameter_unit,
                metadata_label=row.parameter_metadata_label,
                period=row.parameter_period,
                economy=row.parameter_economy,
                household=row.parameter_household,
            )
        items.append(
            MetadataParameterChild(
                path=row.path,
                label=row.label or row.path.rsplit(".", 1)[-1],
                type=row.type,
                child_count=row.child_count,
                parameter=parameter,
            )
        )
    return items


def metadata_economy_options(
    selected: SelectedCatalog, *, regions: list[Region], national_dataset: Dataset
) -> MetadataEconomyOptionsResult:
    """Build economy options from every region, each year and the national dataset.

    The national dataset is the only dataset choice, and it is the default.
    """
    return MetadataEconomyOptionsResult(
        policyengine_version=selected.policyengine_version,
        current_law_id=selected.model_version.current_law_id,
        region=[
            MetadataRegionOption(
                name=region.code,
                label=region.label,
                type=MetadataRegionType(region.region_type.value),
            )
            for region in regions
        ],
        time_period=[
            MetadataTimePeriodOption(name=year, label=str(year))
            for year in selected.model_version.metadata_time_periods
        ],
        datasets=[
            MetadataDatasetOption(
                name=national_dataset.name,
                label=get_dataset_display_label(national_dataset.name),
            )
        ],
    )


def _catalog_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")


def catalog_value_date(start_date: datetime) -> str:
    """Return a value's UTC start day as YYYY-MM-DD, treating a naive time as UTC."""
    if start_date.tzinfo is not None:
        start_date = start_date.astimezone(UTC)
    return start_date.date().isoformat()


def _catalog_parameter(
    parameter: MetadataCatalogParameterRow, values: dict[str, Any]
) -> bytes:
    return _catalog_json(
        {
            "id": str(parameter.id),
            "name": parameter.name,
            "label": parameter.label,
            "description": parameter.description,
            "data_type": parameter.data_type,
            "unit": parameter.unit,
            "metadata_label": parameter.metadata_label,
            "period": parameter.period,
            "economy": parameter.economy,
            "household": parameter.household,
            "values": values,
        }
    )


def metadata_catalog_document(
    selected: SelectedCatalog,
    *,
    parameter_nodes: list[ParameterNode],
    parameters: list[MetadataCatalogParameterRow],
    values: Iterable[tuple[UUID, datetime, Any]],
    variables: list[Variable],
) -> MetadataCatalogDocument:
    """Serialize a catalog version as the model-catalog success envelope.

    values holds (parameter_id, start_date, value) with each parameter's values
    consecutive and oldest first; it is consumed once, as it is read, and each
    parameter is serialized as soon as its values are complete. Parameters,
    nodes and variables appear in the order given (name order).
    """
    parameters_by_id = {parameter.id: parameter for parameter in parameters}
    serialized_by_id: dict[UUID, bytes] = {}
    current_parameter_id: UUID | None = None
    current_values: dict[str, Any] = {}
    for parameter_id, start_date, value in values:
        if parameter_id != current_parameter_id:
            if current_parameter_id in parameters_by_id:
                serialized_by_id[current_parameter_id] = _catalog_parameter(
                    parameters_by_id[current_parameter_id], current_values
                )
            current_parameter_id = parameter_id
            current_values = {}
        current_values[catalog_value_date(start_date)] = value
    if current_parameter_id in parameters_by_id:
        serialized_by_id[current_parameter_id] = _catalog_parameter(
            parameters_by_id[current_parameter_id], current_values
        )

    serialized_parameters = b",".join(
        serialized_by_id.get(parameter.id) or _catalog_parameter(parameter, {})
        for parameter in parameters
    )
    serialized_nodes = _catalog_json(
        [
            {"name": node.name, "label": node.label, "description": node.description}
            for node in parameter_nodes
        ]
    )
    serialized_variables = _catalog_json(
        [metadata_variable(variable).model_dump(mode="json") for variable in variables]
    )
    body = b"".join(
        (
            b'{"status":"ok","message":null,"result":{"policyengine_version":',
            _catalog_json(selected.policyengine_version),
            b',"parameter_nodes":',
            serialized_nodes,
            b',"parameters":[',
            serialized_parameters,
            b'],"variables":',
            serialized_variables,
            b"}}",
        )
    )
    return MetadataCatalogDocument(
        country_id=selected.country_id,
        policyengine_version=selected.policyengine_version,
        body=body,
    )
