"""Reads of the dynamic parameter category, which the metadata service hands on.

They read only ``dynamic_parameters`` and the current-law rows of
``dynamic_parameter_values`` (C1 · 50), so a policy parameter or a dynamic's
own value is never listed or returned (C1 · 51). Each read selects the
catalog version as the policy reads do. The reads of current-law values and
of the tree answer a pruned version with CatalogValuesPrunedError, as their
policy counterparts do (C1 · 46, Q3); the reads of parameter rows, which
pruning keeps, don't.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.metadata.database_connectors.reads_parameter_nodes import (  # noqa: E501  # a dotted module path cannot be wrapped
    read_parameter_node_labels,
)
from policyengine_api.services.v2.metadata.database_connectors.reads_parameters import (
    read_all_dynamic_parameters,
    read_current_law_dynamic_values,
    read_dynamic_parameter,
    read_dynamic_parameter_value,
    read_dynamic_parameter_values,
    read_dynamic_parameters,
)
from policyengine_api.services.v2.metadata.database_connectors.reads_variables import (
    read_variable_enum_values,
)
from policyengine_api.services.v2.metadata.dynamic_parameters.transformations import (
    ancestor_node_names,
    dynamic_parameter_children,
    dynamic_parameter_tree,
    metadata_catalog_dynamic_parameters,
    metadata_dynamic_parameter_value,
)
from policyengine_api.services.v2.metadata.dynamic_parameters.types import (
    DynamicParameterTreeLevel,
)
from policyengine_api.services.v2.metadata.transformations import (
    dated_values_by_parameter_name,
    metadata_parameter,
    page_result,
    parameter_value_selection,
)
from policyengine_api.services.v2.metadata.types import (
    MetadataDetailResult,
    ParameterFilter,
    ParameterValueFilter,
)
from policyengine_api.services.v2.metadata.validators import (
    require_metadata_resource,
)

if TYPE_CHECKING:
    from uuid import UUID

    from policyengine_api.services.v2.metadata.catalog_version_selection.services import (  # noqa: E501  # a dotted module path cannot be wrapped
        MetadataCatalogSelection,
    )
    from policyengine_api.services.v2.metadata.database_session import (
        MetadataDatabaseSession,
    )
    from policyengine_api.services.v2.metadata.dynamic_parameters.types import (
        MetadataCatalogDynamicParametersResult,
    )
    from policyengine_api.services.v2.metadata.types import (
        MetadataCanonicalParameterValue,
        MetadataPageResult,
        MetadataParameterChild,
        MetadataParameterSummary,
    )


class DynamicParameterMetadataService:
    """Sequence the dynamic parameter reads through a request's metadata session.

    The metadata service builds one per request with its own session and
    catalog selection, and exposes it as ``V2MetadataService.dynamic_parameters``.
    List methods page with offset and a limit of 1-500 and report has_more;
    get methods raise MetadataResourceNotFoundError when the selected version
    has no such dynamic parameter or current-law value.
    """

    def __init__(
        self,
        database_session: MetadataDatabaseSession,
        catalogs: MetadataCatalogSelection,
    ) -> None:
        """Bind to the request's session and its catalog selection."""
        self._database_session = database_session
        self._catalogs = catalogs

    def list_dynamic_parameters(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
        parameter_filter: ParameterFilter | None = None,
    ) -> MetadataPageResult[MetadataParameterSummary]:
        """Return a page of the version's dynamic parameters in name order.

        The filter's search keeps parameters whose name, label or description
        contains it, ignoring case, and its names keep only parameters with
        those exact names. No filter lists them all.
        """
        selected = self._catalogs.select_page(
            country_id, policyengine_version, offset=offset, limit=limit
        )
        rows = read_dynamic_parameters(
            self._database_session.session,
            model_version_id=selected.model_version.id,
            offset=offset,
            limit=limit,
            parameter_filter=(
                parameter_filter if parameter_filter is not None else ParameterFilter()
            ),
        )
        return page_result(
            selected,
            [metadata_parameter(row) for row in rows],
            offset=offset,
            limit=limit,
        )

    def get_dynamic_parameter(
        self,
        country_id: str,
        parameter_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataParameterSummary]:
        """Return the version's dynamic parameter with parameter_id.

        A policy parameter's ID, or another version's, is not found.
        """
        selected = self._catalogs.select(country_id, policyengine_version)
        row = require_metadata_resource(
            read_dynamic_parameter(
                self._database_session.session,
                model_version_id=selected.model_version.id,
                parameter_id=parameter_id,
            ),
            description=f"dynamic parameter {parameter_id}",
        )
        return MetadataDetailResult(
            policyengine_version=selected.policyengine_version,
            item=metadata_parameter(row),
        )

    def list_dynamic_parameter_children(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        level: DynamicParameterTreeLevel | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> MetadataPageResult[MetadataParameterChild]:
        """Return a page of one level of the version's dynamic parameter tree.

        The tree is built on this request from the version's dynamic
        parameters, the stored labels of their ancestor nodes and the labels
        of its enum variables' values: three reads after the version's
        selection. The level's parent path "" lists the top level (``gov``,
        plus ``simulation`` for the US); an unknown path has no children.
        With the level's ``settable``, only the children a dynamic may set
        are listed, sorted by label. A pruned version raises
        CatalogValuesPrunedError, as the policy tree's read does; the tree's
        own rows are never pruned, so a selection the process kept from
        before the pruning still answers with them.
        """
        selected_level = level if level is not None else DynamicParameterTreeLevel()
        selected = self._catalogs.select_page(
            country_id,
            policyengine_version,
            offset=offset,
            limit=limit,
            reads_pruned_data=True,
        )
        session = self._database_session.session
        model_version_id = selected.model_version.id
        parameters = read_all_dynamic_parameters(
            session, model_version_id=model_version_id
        )
        tree_rows = dynamic_parameter_tree(
            parameters=parameters,
            node_rows=read_parameter_node_labels(
                session,
                model_version_id=model_version_id,
                node_names=ancestor_node_names(parameters),
            ),
            enum_value_lists=read_variable_enum_values(
                session, model_version_id=model_version_id
            ),
        )
        return page_result(
            selected,
            dynamic_parameter_children(
                tree_rows,
                parameters=parameters,
                level=selected_level,
                offset=offset,
                limit=limit,
            ),
            offset=offset,
            limit=limit,
        )

    def list_dynamic_parameter_values(
        self,
        country_id: str,
        policyengine_version: str | None = None,
        *,
        value_filter: ParameterValueFilter | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> MetadataPageResult[MetadataCanonicalParameterValue]:
        """Return a page of current-law dynamic values, newest first per parameter.

        Values a dynamic sets are never listed. The filter's parameter_id keeps
        one dynamic parameter's values, parameter_names the values of the
        dynamic parameters with those exact names, and current=True those in
        effect on the UTC day of now (today by default).
        """
        selected = self._catalogs.select_page(
            country_id,
            policyengine_version,
            offset=offset,
            limit=limit,
            reads_pruned_data=True,
        )
        rows = read_dynamic_parameter_values(
            self._database_session.session,
            model_version_id=selected.model_version.id,
            selection=parameter_value_selection(
                value_filter if value_filter is not None else ParameterValueFilter()
            ),
            offset=offset,
            limit=limit,
        )
        self._catalogs.require_unpruned(selected, rows_found=bool(rows))
        return page_result(
            selected,
            [metadata_dynamic_parameter_value(row) for row in rows],
            offset=offset,
            limit=limit,
        )

    def get_dynamic_parameter_value(
        self,
        country_id: str,
        value_id: UUID,
        policyengine_version: str | None = None,
    ) -> MetadataDetailResult[MetadataCanonicalParameterValue]:
        """Return the version's current-law dynamic value with value_id.

        A value a dynamic sets, a policy parameter's value, or another
        version's, is not found.
        """
        selected = self._catalogs.select(
            country_id, policyengine_version, reads_pruned_data=True
        )
        value_row = read_dynamic_parameter_value(
            self._database_session.session,
            model_version_id=selected.model_version.id,
            value_id=value_id,
        )
        self._catalogs.require_unpruned(selected, rows_found=value_row is not None)
        row = require_metadata_resource(
            value_row, description=f"dynamic parameter value {value_id}"
        )
        return MetadataDetailResult(
            policyengine_version=selected.policyengine_version,
            item=metadata_dynamic_parameter_value(row),
        )

    def get_catalog_dynamic_parameters(
        self,
        country_id: str,
        policyengine_version: str | None = None,
    ) -> MetadataCatalogDynamicParametersResult:
        """Return every dynamic parameter of the selected version, in name order.

        Each carries its current-law values, and the result carries the
        stored labels of their ancestor nodes.
        """
        selected = self._catalogs.select(
            country_id, policyengine_version, reads_pruned_data=True
        )
        session = self._database_session.session
        model_version_id = selected.model_version.id
        parameters = read_all_dynamic_parameters(
            session, model_version_id=model_version_id
        )
        value_rows = read_current_law_dynamic_values(
            session, model_version_id=model_version_id
        )
        self._catalogs.require_unpruned(
            selected, rows_found=bool(value_rows) or not parameters
        )
        return metadata_catalog_dynamic_parameters(
            selected,
            parameters=parameters,
            values_by_name=dated_values_by_parameter_name(
                value_rows,
                parameter_names={parameter.name for parameter in parameters},
            ),
            node_rows=read_parameter_node_labels(
                session,
                model_version_id=model_version_id,
                node_names=ancestor_node_names(parameters),
            ),
        )
