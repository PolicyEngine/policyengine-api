"""Router-facing services for API v2 metadata reads."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.data.v2.catalog.catalog_selection import (
    SelectedCatalog,
    validate_policyengine_version,
)
from policyengine_api.services.v2.metadata.database_connectors.reads import (
    read_metadata_catalog,
)
from policyengine_api.services.v2.metadata.database_connectors.reads_datasets import (
    read_dataset,
    read_datasets,
    read_input_datasets,
)
from policyengine_api.services.v2.metadata.database_connectors.reads_parameter_nodes import (  # noqa: E501  # a dotted module path cannot be wrapped
    read_parameter_node_labels,
)
from policyengine_api.services.v2.metadata.database_connectors.reads_parameter_tree import (  # noqa: E501  # a dotted module path cannot be wrapped
    read_parameter_children,
)
from policyengine_api.services.v2.metadata.database_connectors.reads_parameters import (
    read_current_law_values_by_parameter_name,
    read_parameter,
    read_parameter_value,
    read_parameter_values,
    read_parameters,
    read_parameters_by_name,
)
from policyengine_api.services.v2.metadata.database_connectors.reads_regions import (
    read_input_dataset,
    read_region,
    read_regions,
)
from policyengine_api.services.v2.metadata.database_connectors.reads_variables import (
    read_all_variables,
    read_variable,
    read_variables,
)
from policyengine_api.services.v2.metadata.transformations import (
    ancestor_paths,
    metadata_catalog_parameters,
    metadata_catalog_variables,
    metadata_dataset,
    metadata_economy_options,
    metadata_model,
    metadata_model_catalog,
    metadata_model_selection,
    metadata_model_version,
    metadata_parameter,
    metadata_parameter_children,
    metadata_parameter_value,
    metadata_region,
    metadata_variable,
    page_result,
    parameter_value_selection,
    part_parameter_paths,
)
from policyengine_api.services.v2.metadata.types import (
    MetadataCanonicalParameterValue,
    MetadataCatalogParametersResult,
    MetadataCatalogVariablesResult,
    MetadataDataset,
    MetadataDetailResult,
    MetadataEconomyOptionsResult,
    MetadataModel,
    MetadataModelCatalogResult,
    MetadataModelSelectionResult,
    MetadataModelVersionDetail,
    MetadataPageResult,
    MetadataParameterChild,
    MetadataParameterSummary,
    MetadataRegion,
    MetadataVariable,
    ParameterValueFilter,
)
from policyengine_api.services.v2.metadata.validators import (
    require_metadata_resource,
    validate_economy_options,
    validate_metadata_page,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from policyengine_api.services.v2.metadata.database_session import (
        MetadataDatabaseSession,
    )


class V2MetadataService:
    """Sequence metadata reads through a request-scoped database session.

    Each read selects the country's catalog for the requested PolicyEngine.py
    version, or for the running version when none is given. List methods page
    with offset and a limit of 1-500 and report has_more; get methods raise
    MetadataResourceNotFoundError when the selected catalog lacks the item.
    """

    def __init__(
        self,
        database_session: MetadataDatabaseSession,
        *,
        running_policyengine_version: str,
    ) -> None:
        """Bind to a request's session and the running PolicyEngine.py version."""
        self._database_session = database_session
        self._running_policyengine_version = validate_policyengine_version(
            running_policyengine_version
        )

    def close(self) -> None:
        """Close the request's database session."""
        self._database_session.close()

    def _select_catalog(
        self, country_id: str, policyengine_version: str | None
    ) -> SelectedCatalog:
        return read_metadata_catalog(
            self._database_session.session,
            country_id=country_id,
            running_policyengine_version=self._running_policyengine_version,
            policyengine_version=policyengine_version,
        )

    def _select_paginated_catalog(
        self,
        country_id: str,
        policyengine_version: str | None,
        *,
        offset: int,
        limit: int,
    ) -> SelectedCatalog:
        validate_metadata_page(offset, limit)
        return self._select_catalog(country_id, policyengine_version)

    def list_models(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> MetadataPageResult[MetadataModel]:
        """Return the catalog's only model on the first page; later pages are empty."""
        selected = self._select_paginated_catalog(
            country_id, policyengine_version, offset=offset, limit=limit
        )
        rows = [metadata_model(selected)] if offset == 0 else []
        return page_result(selected, rows, offset=offset, limit=limit)

    def get_model(
        self,
        country_id: str,
        model_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataModel]:
        """Return the selected catalog's model if its id is model_id."""
        selected = self._select_catalog(country_id, policyengine_version)
        item = require_metadata_resource(
            metadata_model(selected) if selected.model.id == model_id else None,
            description=f"model {model_id}",
        )
        return MetadataDetailResult(
            policyengine_version=selected.policyengine_version, item=item
        )

    def get_model_by_country(
        self, country_id: str, policyengine_version: str | None = None
    ) -> MetadataModelSelectionResult:
        """Return the country's model together with the selected model version."""
        return metadata_model_selection(
            self._select_catalog(country_id, policyengine_version)
        )

    def list_model_versions(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> MetadataPageResult[MetadataModelVersionDetail]:
        """Return the selected version on the first page; later pages are empty."""
        selected = self._select_paginated_catalog(
            country_id, policyengine_version, offset=offset, limit=limit
        )
        rows = [metadata_model_version(selected)] if offset == 0 else []
        return page_result(selected, rows, offset=offset, limit=limit)

    def get_model_version(
        self,
        country_id: str,
        version_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataModelVersionDetail]:
        """Return the selected model version if its id is version_id."""
        selected = self._select_catalog(country_id, policyengine_version)
        item = require_metadata_resource(
            (
                metadata_model_version(selected)
                if selected.model_version.id == version_id
                else None
            ),
            description=f"model version {version_id}",
        )
        return MetadataDetailResult(
            policyengine_version=selected.policyengine_version, item=item
        )

    def list_variables(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
        search: str | None = None,
    ) -> MetadataPageResult[MetadataVariable]:
        """Return a page of the catalog's variables in name order.

        search keeps variables whose name, label or description contains it,
        ignoring case.
        """
        selected = self._select_paginated_catalog(
            country_id, policyengine_version, offset=offset, limit=limit
        )
        rows = read_variables(
            self._database_session.session,
            model_version_id=selected.model_version.id,
            offset=offset,
            limit=limit,
            search=search,
        )
        return page_result(
            selected,
            [metadata_variable(row) for row in rows],
            offset=offset,
            limit=limit,
        )

    def get_variable(
        self,
        country_id: str,
        variable_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataVariable]:
        """Return the variable with variable_id if it is in the selected catalog."""
        selected = self._select_catalog(country_id, policyengine_version)
        row = require_metadata_resource(
            read_variable(
                self._database_session.session,
                model_version_id=selected.model_version.id,
                variable_id=variable_id,
            ),
            description=f"variable {variable_id}",
        )
        return MetadataDetailResult(
            policyengine_version=selected.policyengine_version,
            item=metadata_variable(row),
        )

    def list_parameters(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
        search: str | None = None,
    ) -> MetadataPageResult[MetadataParameterSummary]:
        """Return a page of the catalog's parameters in name order.

        search keeps parameters whose name, label or description contains it,
        ignoring case.
        """
        selected = self._select_paginated_catalog(
            country_id, policyengine_version, offset=offset, limit=limit
        )
        rows = read_parameters(
            self._database_session.session,
            model_version_id=selected.model_version.id,
            offset=offset,
            limit=limit,
            search=search,
        )
        return page_result(
            selected,
            [metadata_parameter(row) for row in rows],
            offset=offset,
            limit=limit,
        )

    def get_parameter(
        self,
        country_id: str,
        parameter_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataParameterSummary]:
        """Return the parameter with parameter_id if it is in the selected catalog."""
        selected = self._select_catalog(country_id, policyengine_version)
        row = require_metadata_resource(
            read_parameter(
                self._database_session.session,
                model_version_id=selected.model_version.id,
                parameter_id=parameter_id,
            ),
            description=f"parameter {parameter_id}",
        )
        return MetadataDetailResult(
            policyengine_version=selected.policyengine_version,
            item=metadata_parameter(row),
        )

    def list_parameter_children(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        parent_path: str = "",
        offset: int = 0,
        limit: int = 100,
    ) -> MetadataPageResult[MetadataParameterChild]:
        """Return a page of the direct children of parent_path in the parameter tree.

        An empty parent_path lists the top-level children. A child is a parameter
        when it is a leaf with a parameter row, and a node otherwise.
        """
        selected = self._select_paginated_catalog(
            country_id, policyengine_version, offset=offset, limit=limit
        )
        rows = read_parameter_children(
            self._database_session.session,
            model_version_id=selected.model_version.id,
            parent_path=parent_path,
            offset=offset,
            limit=limit,
        )
        return page_result(
            selected,
            metadata_parameter_children(rows),
            offset=offset,
            limit=limit,
        )

    def list_parameter_values(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        value_filter: ParameterValueFilter | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> MetadataPageResult[MetadataCanonicalParameterValue]:
        """Return a page of current-law parameter values, newest first per parameter.

        Values belonging to a reform or dynamic are never listed. The filter's
        parameter_id keeps one parameter's values, and current=True keeps those in
        effect on the UTC day of now (today by default). No filter lists them all.
        """
        selected = self._select_paginated_catalog(
            country_id, policyengine_version, offset=offset, limit=limit
        )
        rows = read_parameter_values(
            self._database_session.session,
            model_version_id=selected.model_version.id,
            selection=parameter_value_selection(
                value_filter if value_filter is not None else ParameterValueFilter()
            ),
            offset=offset,
            limit=limit,
        )
        return page_result(
            selected,
            [metadata_parameter_value(row) for row in rows],
            offset=offset,
            limit=limit,
        )

    def get_parameter_value(
        self,
        country_id: str,
        value_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataCanonicalParameterValue]:
        """Return the current-law value with value_id if it is in the selected catalog.

        Values belonging to a reform or dynamic are never returned.
        """
        selected = self._select_catalog(country_id, policyengine_version)
        row = require_metadata_resource(
            read_parameter_value(
                self._database_session.session,
                model_version_id=selected.model_version.id,
                value_id=value_id,
            ),
            description=f"parameter value {value_id}",
        )
        return MetadataDetailResult(
            policyengine_version=selected.policyengine_version,
            item=metadata_parameter_value(row),
        )

    def list_datasets(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> MetadataPageResult[MetadataDataset]:
        """Return a page of the catalog's logical input datasets in name order.

        Output datasets and datasets with a storage path are never listed.
        """
        selected = self._select_paginated_catalog(
            country_id, policyengine_version, offset=offset, limit=limit
        )
        rows = read_datasets(
            self._database_session.session,
            model_version_id=selected.model_version.id,
            offset=offset,
            limit=limit,
        )
        return page_result(
            selected,
            [metadata_dataset(row) for row in rows],
            offset=offset,
            limit=limit,
        )

    def get_dataset(
        self,
        country_id: str,
        dataset_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataDataset]:
        """Return the logical input dataset with dataset_id in the selected catalog."""
        selected = self._select_catalog(country_id, policyengine_version)
        row = require_metadata_resource(
            read_dataset(
                self._database_session.session,
                model_version_id=selected.model_version.id,
                dataset_id=dataset_id,
            ),
            description=f"dataset {dataset_id}",
        )
        return MetadataDetailResult(
            policyengine_version=selected.policyengine_version,
            item=metadata_dataset(row),
        )

    def list_regions(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        region_type: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> MetadataPageResult[MetadataRegion]:
        """Return a page of the catalog's regions by code, optionally of one type."""
        selected = self._select_paginated_catalog(
            country_id, policyengine_version, offset=offset, limit=limit
        )
        rows = read_regions(
            self._database_session.session,
            model_version_id=selected.model_version.id,
            region_type=region_type,
            offset=offset,
            limit=limit,
        )
        return page_result(
            selected,
            [metadata_region(row) for row in rows],
            offset=offset,
            limit=limit,
        )

    def get_region(
        self,
        country_id: str,
        region_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataRegion]:
        """Return the region with region_id from the selected catalog."""
        selected = self._select_catalog(country_id, policyengine_version)
        row = require_metadata_resource(
            read_region(
                self._database_session.session,
                model_version_id=selected.model_version.id,
                region_id=region_id,
            ),
            description=f"region {region_id}",
        )
        return MetadataDetailResult(
            policyengine_version=selected.policyengine_version,
            item=metadata_region(row),
        )

    def get_region_by_code(
        self,
        country_id: str,
        region_code: str,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataRegion]:
        """Return the region with region_code from the selected catalog."""
        selected = self._select_catalog(country_id, policyengine_version)
        row = require_metadata_resource(
            read_region(
                self._database_session.session,
                model_version_id=selected.model_version.id,
                region_code=region_code,
            ),
            description=f"region {region_code!r}",
        )
        return MetadataDetailResult(
            policyengine_version=selected.policyengine_version,
            item=metadata_region(row),
        )

    def get_economy_options(
        self, country_id: str, policyengine_version: str | None = None
    ) -> MetadataEconomyOptionsResult:
        """Return the region, year and dataset choices for an economy calculation.

        Raise MetadataCatalogUnavailableError when the catalog lacks the national
        region, its default input dataset, the current-law id or the years.
        """
        selected = self._select_catalog(country_id, policyengine_version)
        regions = read_regions(
            self._database_session.session,
            model_version_id=selected.model_version.id,
        )
        national_region = next(
            (region for region in regions if region.code == country_id), None
        )
        national_dataset = (
            read_input_dataset(
                self._database_session.session,
                model_version_id=selected.model_version.id,
                dataset_id=national_region.default_dataset_id,
            )
            if national_region is not None
            else None
        )
        dataset = validate_economy_options(
            selected,
            country_id=country_id,
            regions=regions,
            national_dataset=national_dataset,
        )
        return metadata_economy_options(
            selected, regions=regions, national_dataset=dataset
        )

    def get_model_catalog(
        self, country_id: str, policyengine_version: str | None = None
    ) -> MetadataModelCatalogResult:
        """Return the small parts of the selected catalog version.

        They are the model and model version, entities, basic inputs, every
        region and logical input dataset, and the economy choices. A catalog
        without regions offers no economy calculation, so its choices are
        empty; one with regions raises MetadataCatalogUnavailableError when it
        lacks the national region, its default dataset or the model-version
        options, as get_economy_options does.
        """
        selected = self._select_catalog(country_id, policyengine_version)
        session = self._database_session.session
        regions = read_regions(session, model_version_id=selected.model_version.id)
        datasets = read_input_datasets(
            session, model_version_id=selected.model_version.id
        )
        national_dataset = None
        if regions:
            national_region = next(
                (region for region in regions if region.code == country_id), None
            )
            national_dataset = validate_economy_options(
                selected,
                country_id=country_id,
                regions=regions,
                national_dataset=(
                    next(
                        (
                            dataset
                            for dataset in datasets
                            if dataset.id == national_region.default_dataset_id
                        ),
                        None,
                    )
                    if national_region is not None
                    else None
                ),
            )
        return metadata_model_catalog(
            selected,
            regions=regions,
            datasets=datasets,
            national_dataset=national_dataset,
        )

    def get_catalog_variables(
        self, country_id: str, policyengine_version: str | None = None
    ) -> MetadataCatalogVariablesResult:
        """Return every variable of the selected catalog version, in name order.

        It also returns the current-law values of each parameter a variable's
        adds or subtracts names, so a client can pick the list for any year.
        """
        selected = self._select_catalog(country_id, policyengine_version)
        session = self._database_session.session
        variables = read_all_variables(
            session, model_version_id=selected.model_version.id
        )
        part_values = read_current_law_values_by_parameter_name(
            session,
            model_version_id=selected.model_version.id,
            parameter_names=part_parameter_paths(variables),
        )
        return metadata_catalog_variables(
            selected, variables=variables, part_values=part_values
        )

    def get_catalog_parameters(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        names: Sequence[str],
    ) -> MetadataCatalogParametersResult:
        """Return the named parameters of the selected version, in name order.

        Each carries its current-law values, and the result carries the stored
        labels of their ancestor nodes and the requested names the version
        lacks. Repeated names count once.
        """
        selected = self._select_catalog(country_id, policyengine_version)
        session = self._database_session.session
        model_version_id = selected.model_version.id
        requested_names = set(names)
        parameters = read_parameters_by_name(
            session, model_version_id=model_version_id, parameter_names=requested_names
        )
        found_names = {parameter.name for parameter in parameters}
        value_rows = read_current_law_values_by_parameter_name(
            session, model_version_id=model_version_id, parameter_names=found_names
        )
        node_rows = read_parameter_node_labels(
            session,
            model_version_id=model_version_id,
            node_names={
                ancestor for name in found_names for ancestor in ancestor_paths(name)
            },
        )
        return metadata_catalog_parameters(
            selected,
            requested_names=requested_names,
            parameters=parameters,
            value_rows=value_rows,
            node_rows=node_rows,
        )
