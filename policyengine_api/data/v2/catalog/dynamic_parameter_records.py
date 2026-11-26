"""Which records of a country's catalog are model assumptions (C1 · 50).

Catalog publication stores a version's model assumptions
(``policyengine_api.dynamic_parameters``) in ``dynamic_parameters`` and their
current-law values in ``dynamic_parameter_values``, and every other parameter
in ``parameters``. The policy tree and the search file hold only the other
parameters and the nodes outside the folders that hold only assumptions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.data.v2.catalog.publication_types import (
    CatalogPublicationError,
)
from policyengine_api.dynamic_parameters import (
    is_dynamic_parameter,
    is_dynamic_parameter_path,
)
from policyengine_api.supported_countries import SUPPORTED_COUNTRY_IDS

if TYPE_CHECKING:
    from policyengine_api.data.v2.catalog.records import (
        CountryCatalog,
        ParameterNodeRecord,
        ParameterRecord,
    )
    from policyengine_api.supported_countries import SupportedCountryId


def supported_country_id(country_id: str) -> SupportedCountryId:
    """Return a catalog's country as a supported one, or raise.

    Raise CatalogPublicationError for a country with no model assumption
    prefixes, which publication cannot classify.
    """
    for supported in SUPPORTED_COUNTRY_IDS:
        if supported == country_id:
            return supported
    msg = f"the catalog country {country_id!r} is not a supported country"
    raise CatalogPublicationError(msg)


def is_dynamic_record(country_id: str, parameter_name: str) -> bool:
    """Return whether the country's parameter is a model assumption."""
    return is_dynamic_parameter(supported_country_id(country_id), parameter_name)


def is_dynamic_path(country_id: str, path: str) -> bool:
    """Return whether a node or parameter path holds only model assumptions."""
    return is_dynamic_parameter_path(supported_country_id(country_id), path)


def policy_parameter_records(country: CountryCatalog) -> tuple[ParameterRecord, ...]:
    """Return the country's parameters that are not model assumptions."""
    return tuple(
        parameter
        for parameter in country.parameters
        if not is_dynamic_record(country.country_id, parameter.name)
    )


def policy_node_records(country: CountryCatalog) -> tuple[ParameterNodeRecord, ...]:
    """Return the country's nodes outside the folders of model assumptions."""
    return tuple(
        node
        for node in country.parameter_nodes
        if not is_dynamic_path(country.country_id, node.name)
    )
