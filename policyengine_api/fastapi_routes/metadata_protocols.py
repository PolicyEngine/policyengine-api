"""Interfaces of the metadata readers that native FastAPI routes depend on."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from policyengine_api.json_types import JSONObject
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
        ParameterFilter,
        ParameterValueFilter,
    )


class MetadataReader(Protocol):
    """Read the already-loaded metadata document for a country."""

    def get_metadata(self, country_id: str) -> JSONObject:
        """Return the loaded v1 metadata document for a supported country."""
        ...


class V2MetadataResourceReader(Protocol):
    """Own the database session used by one v2 metadata resource request.

    Every read selects one country catalog: the one published for
    ``policyengine_version``, or the running package's catalog when it is None.
    Absent resources raise ``MetadataResourceNotFoundError``, and list reads
    raise ``InvalidMetadataPageError`` unless ``offset >= 0`` and
    ``1 <= limit <= 500``.
    """

    def close(self) -> None:
        """Release the request's database session, even after a failed read."""
        ...

    def list_models(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> MetadataPageResult[MetadataModel]:
        """Return a page holding the selected catalog's single tax-benefit model."""
        ...

    def get_model(
        self,
        country_id: str,
        model_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataModel]:
        """Return the selected catalog's model when ``model_id`` is its UUID."""
        ...

    def get_model_by_country(
        self,
        country_id: str,
        policyengine_version: str | None = None,
    ) -> MetadataModelSelectionResult:
        """Return the country's model and the selected catalog's model version."""
        ...

    def list_model_versions(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> MetadataPageResult[MetadataModelVersionDetail]:
        """Return a page holding the selected catalog's single model version."""
        ...

    def get_model_version(
        self,
        country_id: str,
        version_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataModelVersionDetail]:
        """Return the selected model version when ``version_id`` is its UUID."""
        ...

    def list_variables(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
        search: str | None = None,
    ) -> MetadataPageResult[MetadataVariable]:
        """Return variables in name order, optionally filtered by ``search``.

        ``search`` is a case-insensitive substring of the name, label or description.
        """
        ...

    def get_variable(
        self,
        country_id: str,
        variable_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataVariable]:
        """Return one variable of the selected catalog by UUID."""
        ...

    def list_parameters(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
        parameter_filter: ParameterFilter | None = None,
    ) -> MetadataPageResult[MetadataParameterSummary]:
        """Return parameters in name order, optionally filtered.

        The filter's ``search`` is a case-insensitive substring of the name,
        label or description; its ``names`` keep only those exact names.
        """
        ...

    def get_parameter(
        self,
        country_id: str,
        parameter_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataParameterSummary]:
        """Return one parameter of the selected catalog by UUID."""
        ...

    def list_parameter_children(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        parent_path: str = "",
        offset: int = 0,
        limit: int = 100,
    ) -> MetadataPageResult[MetadataParameterChild]:
        """Return the nodes and parameters one level below ``parent_path``.

        An empty ``parent_path`` lists the top level of the parameter tree.
        """
        ...

    def list_parameter_values(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        value_filter: ParameterValueFilter | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> MetadataPageResult[MetadataCanonicalParameterValue]:
        """Return canonical values, optionally for one or several parameters.

        The filter's ``parameter_id`` or ``parameter_names`` select parameters.
        With its ``current``, only values in effect on the UTC day of its
        ``now`` (default: the present) are returned.
        """
        ...

    def get_parameter_value(
        self,
        country_id: str,
        value_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataCanonicalParameterValue]:
        """Return one canonical parameter value of the selected catalog by UUID."""
        ...

    def list_datasets(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> MetadataPageResult[MetadataDataset]:
        """Return the logical input datasets of the selected catalog."""
        ...

    def get_dataset(
        self,
        country_id: str,
        dataset_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataDataset]:
        """Return one logical input dataset of the selected catalog by UUID."""
        ...

    def list_regions(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        region_type: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> MetadataPageResult[MetadataRegion]:
        """Return the catalog's regions by code, optionally of one ``region_type``."""
        ...

    def get_region(
        self,
        country_id: str,
        region_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataRegion]:
        """Return one region of the selected catalog by UUID."""
        ...

    def get_region_by_code(
        self,
        country_id: str,
        region_code: str,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataRegion]:
        """Return one region by code; the national region's code is the country id."""
        ...

    def get_economy_options(
        self,
        country_id: str,
        policyengine_version: str | None = None,
    ) -> MetadataEconomyOptionsResult:
        """Return the options a client needs to configure an economy comparison.

        These are the current-law policy id, regions, years and datasets.

        Raise ``MetadataCatalogUnavailableError`` when the national region, its
        dataset or the model version's options are missing from the catalog.
        """
        ...

    def get_model_catalog(
        self,
        country_id: str,
        policyengine_version: str | None = None,
    ) -> MetadataModelCatalogResult:
        """Return the small parts of the selected catalog version.

        These are the model and model version, entities, basic inputs, regions,
        logical input datasets and economy choices, which are empty for a
        catalog without regions. Raise ``MetadataCatalogUnavailableError`` when
        a catalog with regions lacks what ``get_economy_options`` needs.
        """
        ...

    def get_catalog_variables(
        self,
        country_id: str,
        policyengine_version: str | None = None,
    ) -> MetadataCatalogVariablesResult:
        """Return every variable of the selected catalog version, in name order.

        It also carries the current-law values of each parameter a variable's
        adds or subtracts names.
        """
        ...

    def get_catalog_parameters(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        names: Sequence[str],
    ) -> MetadataCatalogParametersResult:
        """Return the named parameters of the selected version, in name order.

        Each carries its current-law values; the result also carries the
        stored labels of their ancestor nodes and the names the version lacks.
        """
        ...
