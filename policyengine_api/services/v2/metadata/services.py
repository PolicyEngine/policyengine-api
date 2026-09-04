"""Router-facing services for API v2 metadata reads."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

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
)
from policyengine_api.services.v2.metadata.database_connectors.reads_parameter_tree import (
    read_parameter_children,
)
from policyengine_api.services.v2.metadata.database_connectors.reads_parameters import (
    read_parameter,
    read_parameter_value,
    read_parameter_values,
    read_parameters,
)
from policyengine_api.services.v2.metadata.database_connectors.reads_regions import (
    read_input_dataset,
    read_region,
    read_regions,
)
from policyengine_api.services.v2.metadata.database_connectors.reads_variables import (
    read_variable,
    read_variables,
)
from policyengine_api.services.v2.metadata.database_session import (
    MetadataDatabaseSession,
)
from policyengine_api.services.v2.metadata.transformations import (
    metadata_dataset,
    metadata_economy_options,
    metadata_model,
    metadata_model_selection,
    metadata_model_version,
    metadata_parameter,
    metadata_parameter_children,
    metadata_parameter_value,
    metadata_region,
    metadata_variable,
    page_result,
    utc_day_start,
)
from policyengine_api.services.v2.metadata.types import (
    MetadataCanonicalParameterValue,
    MetadataDataset,
    MetadataDetailResult,
    MetadataEconomyOptionsResult,
    MetadataModel,
    MetadataModelSelectionResult,
    MetadataModelVersionDetail,
    MetadataPageResult,
    MetadataParameterChild,
    MetadataParameterSummary,
    MetadataRegion,
    MetadataVariable,
)
from policyengine_api.services.v2.metadata.validators import (
    require_metadata_resource,
    validate_economy_options,
    validate_metadata_page,
)


class V2MetadataService:
    """Sequence metadata reads through a request-scoped database session."""

    def __init__(
        self,
        database_session: MetadataDatabaseSession,
        *,
        running_policyengine_version: str,
    ) -> None:
        self._database_session = database_session
        self._running_policyengine_version = validate_policyengine_version(
            running_policyengine_version
        )

    def close(self) -> None:
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
        selected = self._select_paginated_catalog(
            country_id, policyengine_version, offset=offset, limit=limit
        )
        rows = read_parameter_children(
            self._database_session.session,
            model_version_id=selected.model_version.id,
            parent_path=parent_path,
            dialect=self._database_session.dialect_name,
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
        parameter_id: UUID | None = None,
        current: bool = False,
        offset: int = 0,
        limit: int = 100,
        now: datetime | None = None,
    ) -> MetadataPageResult[MetadataCanonicalParameterValue]:
        selected = self._select_paginated_catalog(
            country_id, policyengine_version, offset=offset, limit=limit
        )
        selected_day = (
            utc_day_start(now or datetime.now(timezone.utc)) if current else None
        )
        rows = read_parameter_values(
            self._database_session.session,
            model_version_id=selected.model_version.id,
            parameter_id=parameter_id,
            selected_day=selected_day,
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
