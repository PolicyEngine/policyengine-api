"""Pure representation transformations for v2 metadata operations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TypeVar

from policyengine_api.dataset_display import get_dataset_display_label
from policyengine_api.services.v2.metadata.types import (
    CurrentLawValueRow,
    FoundParameters,
    MetadataCanonicalParameterValue,
    MetadataCatalogParameter,
    MetadataCatalogParametersResult,
    MetadataCatalogVariablesResult,
    MetadataDataset,
    MetadataDatasetOption,
    MetadataDatedValue,
    MetadataEconomyOptions,
    MetadataEconomyOptionsResult,
    MetadataEntity,
    MetadataEnumValue,
    MetadataModel,
    MetadataModelCatalogResult,
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
    ParameterNodeLabelRow,
    ParameterValueSelection,
)

if TYPE_CHECKING:
    from policyengine_api.data.v2.catalog.catalog_selection import SelectedCatalog
    from policyengine_api.data.v2.models import (
        Dataset,
        Parameter,
        ParameterValue,
        Region,
        Variable,
    )
    from policyengine_api.services.v2.metadata.types import ParameterValueFilter

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
        is_input_variable=variable.is_input_variable,
        hidden_input=variable.hidden_input,
        module_name=variable.module_name,
        adds_parameter_path=variable.adds_parameter_path,
        subtracts_parameter_path=variable.subtracts_parameter_path,
        enum_values=(
            None
            if variable.enum_values is None
            else [
                MetadataEnumValue.model_validate(enum_value)
                for enum_value in variable.enum_values
            ]
        ),
    )


def part_parameter_paths(variables: list[Variable]) -> set[str]:
    """Return every parameter path the variables' adds or subtracts names."""
    return {
        path
        for variable in variables
        for path in (variable.adds_parameter_path, variable.subtracts_parameter_path)
        if path is not None
    }


def metadata_catalog_variables(
    selected: SelectedCatalog,
    *,
    variables: list[Variable],
    part_paths: set[str],
    part_values: list[CurrentLawValueRow],
) -> MetadataCatalogVariablesResult:
    """Build every variable of the selected version and its part parameters' values.

    part_paths holds part_parameter_paths of the variables, and part_values the
    current-law values of those parameters in name and start-date order. Each
    path gets an entry, empty when no value carries its name.
    """
    values_by_path = _dated_values_by_parameter_name(
        part_values, parameter_names=part_paths
    )
    return MetadataCatalogVariablesResult(
        policyengine_version=selected.policyengine_version,
        catalog_format=selected.model_version.catalog_format,
        variables=[metadata_variable(variable) for variable in variables],
        part_parameter_values=values_by_path,
    )


def _dated_values_by_parameter_name(
    value_rows: list[CurrentLawValueRow], *, parameter_names: set[str]
) -> dict[str, list[MetadataDatedValue]]:
    """Group value rows by parameter name, with an empty list for each other name.

    value_rows are in parameter-name and start-date order.
    """
    values_by_name: dict[str, list[MetadataDatedValue]] = {
        name: [] for name in sorted(parameter_names)
    }
    for row in value_rows:
        values_by_name.setdefault(row.name, []).append(
            MetadataDatedValue(
                start_date=as_utc(row.start_date),
                end_date=None if row.end_date is None else as_utc(row.end_date),
                value=row.value_json,
            )
        )
    return values_by_name


def metadata_parameter(parameter: Parameter) -> MetadataParameterSummary:
    """Return the API representation of a stored parameter."""
    return MetadataParameterSummary(
        id=parameter.id,
        name=parameter.name,
        label=parameter.label,
        description=parameter.description,
        data_type=parameter.data_type,
        unit=parameter.unit,
        economy=parameter.economy,
        household=parameter.household,
    )


def ancestor_paths(parameter_name: str) -> list[str]:
    """Return the paths of every node above parameter_name, from the root down.

    A dot separates a child, and so does the ``[`` of a bracket index:
    ``gov.tax.rates[0].rate`` has the ancestors ``gov``, ``gov.tax``,
    ``gov.tax.rates`` and ``gov.tax.rates[0]``.
    """
    return [
        parameter_name[:position]
        for position, character in enumerate(parameter_name)
        if character in ".[" and position > 0
    ]


def metadata_catalog_parameters(
    selected: SelectedCatalog,
    *,
    requested_names: set[str],
    found_parameters: FoundParameters,
    value_rows: list[CurrentLawValueRow],
    node_rows: list[ParameterNodeLabelRow],
) -> MetadataCatalogParametersResult:
    """Build the requested parameters with their values and ancestor labels.

    value_rows are the found parameters' current-law values and node_rows the
    stored labels of their ancestor nodes.
    """
    parameters = found_parameters.parameters
    found_names = found_parameters.names
    values_by_name = _dated_values_by_parameter_name(
        value_rows, parameter_names=found_names
    )
    return MetadataCatalogParametersResult(
        policyengine_version=selected.policyengine_version,
        catalog_format=selected.model_version.catalog_format,
        parameters=[
            MetadataCatalogParameter(
                **metadata_parameter(parameter).model_dump(),
                values=values_by_name[parameter.name],
            )
            for parameter in parameters
        ],
        node_labels={row.name: row.label for row in node_rows},
        missing_names=sorted(requested_names - found_names),
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


def as_utc(moment: datetime) -> datetime:
    """Return moment in UTC, treating a naive time as UTC.

    The database may return times in its session's time zone (or, in SQLite,
    without one); serving them in UTC keeps a response's bytes, and so its
    ETag, the same whatever that setting is.
    """
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def utc_day_start(selected_time: datetime) -> datetime:
    """Return midnight UTC on the day of selected_time, treating a naive time as UTC."""
    if selected_time.tzinfo is None:
        selected_time = selected_time.replace(tzinfo=UTC)
    return selected_time.astimezone(UTC).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def parameter_value_selection(
    value_filter: ParameterValueFilter,
) -> ParameterValueSelection:
    """Resolve a listing's filter to the parameter and day its read selects.

    A current filter selects the UTC day of its ``now``, or of the present.
    """
    selected_day = (
        utc_day_start(value_filter.now or datetime.now(UTC))
        if value_filter.current
        else None
    )
    return ParameterValueSelection(
        parameter_id=value_filter.parameter_id,
        selected_day=selected_day,
        parameter_names=value_filter.parameter_names,
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


def national_region(regions: list[Region], country_id: str) -> Region | None:
    """Return the country's national region (its code is the country ID), or None."""
    return next((region for region in regions if region.code == country_id), None)


def metadata_economy_options(
    selected: SelectedCatalog, *, regions: list[Region], national_dataset: Dataset
) -> MetadataEconomyOptionsResult:
    """Build economy options from every region, each year and the national dataset.

    The national dataset is the only dataset choice, and it is the default.
    """
    options = _economy_option_lists(
        selected, regions=regions, national_dataset=national_dataset
    )
    return MetadataEconomyOptionsResult(
        policyengine_version=selected.policyengine_version,
        current_law_id=selected.model_version.current_law_id,
        region=options.region,
        time_period=options.time_period,
        datasets=options.datasets,
    )


def _economy_option_lists(
    selected: SelectedCatalog, *, regions: list[Region], national_dataset: Dataset
) -> MetadataEconomyOptions:
    return MetadataEconomyOptions(
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


def metadata_model_catalog(
    selected: SelectedCatalog,
    *,
    regions: list[Region],
    datasets: list[Dataset],
    national_dataset: Dataset | None,
) -> MetadataModelCatalogResult:
    """Build the small parts of the selected catalog version.

    Without a national dataset (a catalog without regions) the economy choices
    are empty. Entities and basic inputs a version published before catalog
    format 2 lacks are empty lists.
    """
    model_version = selected.model_version
    return MetadataModelCatalogResult(
        policyengine_version=selected.policyengine_version,
        catalog_format=model_version.catalog_format,
        model=metadata_model(selected),
        model_version=metadata_model_version(selected),
        entities=[
            MetadataEntity.model_validate(entity)
            for entity in model_version.entities or []
        ],
        basic_inputs=list(model_version.basic_inputs or []),
        regions=[metadata_region(region) for region in regions],
        datasets=[metadata_dataset(dataset) for dataset in datasets],
        economy_options=(
            _economy_option_lists(
                selected, regions=regions, national_dataset=national_dataset
            )
            if national_dataset is not None
            else MetadataEconomyOptions(region=[], time_period=[], datasets=[])
        ),
    )
