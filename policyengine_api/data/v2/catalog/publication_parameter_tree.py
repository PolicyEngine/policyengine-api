"""Write the parameter tree of the installed catalog's versions.

Publication writes the tree of each country version in the catalog it
publishes, which is extracted from the installed packages: versions it
publishes now, and the installed version when an earlier release stored it with
catalog format 2 but without a tree. An installed version stored before catalog
format 2 gets none, since its parameter rows store no flags. The rows are built
from the catalog's own parameter and node records (``parameter_tree``), never
from rows an earlier release stored. Only
the stored parameters' IDs are read, by name, so tree rows reference the stored
parameters; publication has already checked that those stored rows match the
catalog. Writing only inserts rows for a version that has no tree; no other
table changes.

Other stored versions get no tree here: deriving their rows from what earlier
releases stored would be a data migration, which the migration rules leave to
a human decision.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import sqlalchemy as sa
from sqlmodel import col

from policyengine_api.data.v2.catalog.parameter_tree import (
    ParameterTreeChildRow,
    TreeNodeSource,
    TreeParameterSource,
    build_parameter_tree,
)
from policyengine_api.data.v2.catalog.publication_reconciliation import (
    StoredVersion,
    stored_version,
)
from policyengine_api.data.v2.catalog.publication_staging import (
    column_names,
    copy_rows,
)
from policyengine_api.data.v2.catalog.publication_types import (
    CatalogPublicationError,
)
from policyengine_api.data.v2.models import (
    Parameter,
    ParameterTreeChild,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from uuid import UUID

    from sqlmodel import Session

    from policyengine_api.data.v2.catalog.records import CountryCatalog


def _version_for_tree(session: Session, country: CountryCatalog) -> StoredVersion:
    stored = stored_version(session, country)
    if stored is None:
        msg = (
            f"the {country.country_id} catalog version "
            f"{country.model_version.version} is not stored"
        )
        raise CatalogPublicationError(msg)
    return stored


def _has_tree(session: Session, version_id: UUID) -> bool:
    return bool(
        session.execute(
            sa.select(
                sa.exists().where(
                    col(ParameterTreeChild.tax_benefit_model_version_id) == version_id
                )
            )
        ).scalar_one()
    )


def _stored_parameter_ids(session: Session, version_id: UUID) -> dict[str, UUID]:
    return {
        row.name: row.id
        for row in session.execute(
            sa.select(col(Parameter.name), col(Parameter.id)).where(
                col(Parameter.tax_benefit_model_version_id) == version_id
            )
        )
    }


def catalog_parameter_tree(
    country: CountryCatalog, stored_parameter_ids: dict[str, UUID]
) -> tuple[ParameterTreeChildRow, ...]:
    """Build a country version's tree from its catalog records.

    Each parameter row references the stored parameter of the same name;
    raise CatalogPublicationError if a catalog parameter has no stored row.
    """
    missing = [
        parameter.name
        for parameter in country.parameters
        if parameter.name not in stored_parameter_ids
    ]
    if missing:
        msg = (
            f"the stored {country.country_id} catalog version "
            f"{country.model_version.version} lacks the parameter {missing[0]}"
        )
        raise CatalogPublicationError(msg)
    return build_parameter_tree(
        nodes=[
            TreeNodeSource(name=node.name, label=node.label)
            for node in country.parameter_nodes
        ],
        parameters=[
            TreeParameterSource(
                id=stored_parameter_ids[parameter.name],
                name=parameter.name,
                label=parameter.label,
                economy=parameter.economy,
                household=parameter.household,
            )
            for parameter in country.parameters
        ],
        enum_labels=enum_value_labels(country),
    )


def enum_value_labels(country: CountryCatalog) -> dict[str, frozenset[str]]:
    """Return the labels the country's enum variables give each value's name."""
    labels: dict[str, set[str]] = defaultdict(set)
    for variable in country.variables:
        for enum_value in variable.enum_values or ():
            if enum_value.label is not None:
                labels[enum_value.value].add(str(enum_value.label))
    return {value: frozenset(names) for value, names in labels.items()}


def _table_rows(
    version_id: UUID,
    rows: tuple[ParameterTreeChildRow, ...],
) -> Iterator[tuple[object, ...]]:
    created_at = datetime.now(UTC)
    names = column_names(ParameterTreeChild)
    for row in rows:
        values: dict[str, object] = {
            "id": uuid4(),
            "created_at": created_at,
            "tax_benefit_model_version_id": version_id,
            "parent_path": row.parent_path,
            "path": row.path,
            "position": row.position,
            "label": row.label,
            "child_type": row.child_type,
            "child_count": row.child_count,
            "reform_position": row.reform_position,
            "reform_child_count": row.reform_child_count,
            "parameter_id": row.parameter_id,
            "economy": row.economy,
            "household": row.household,
        }
        yield tuple(values[name] for name in names)


def write_parameter_trees(
    session: Session,
    countries: Sequence[CountryCatalog],
) -> tuple[tuple[str, str, int], ...]:
    """Write the tree of each catalog country's stored version that has none.

    A version stored before catalog format 2 gets none: its parameter rows
    store no flags, so a tree built with the catalog's flags would not match
    them. Returns the model name, version and number of rows written for each
    version, in model name order. Runs inside publication's transaction and
    advisory lock, after the countries' versions are stored and checked.
    """
    written = []
    for country in countries:
        stored = _version_for_tree(session, country)
        if stored.catalog_format is None or _has_tree(session, stored.id):
            continue
        rows = catalog_parameter_tree(
            country, _stored_parameter_ids(session, stored.id)
        )
        count = copy_rows(
            session,
            model=ParameterTreeChild,
            rows=_table_rows(stored.id, rows),
        )
        written.append((country.model.name, country.model_version.version, count))
    return tuple(sorted(written))


def assert_parameter_trees_written(
    session: Session,
    countries: Sequence[CountryCatalog],
) -> None:
    """Raise CatalogPublicationError if a catalog country's version has no tree.

    Versions stored before catalog format 2 are exempt: they get no tree.
    """
    for country in countries:
        stored = _version_for_tree(session, country)
        if stored.catalog_format is not None and not _has_tree(session, stored.id):
            msg = (
                f"the {country.country_id} catalog version "
                f"{country.model_version.version} has no parameter tree"
            )
            raise CatalogPublicationError(msg)
