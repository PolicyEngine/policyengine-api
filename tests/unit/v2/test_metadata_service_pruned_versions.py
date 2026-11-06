"""Metadata reads of a catalog version whose current-law values pruning removed.

Catalog publication prunes older catalog versions: it deletes their current-law
parameter values, parameter tree rows and parameter search file, and records
when on the model version (``catalog_values_pruned_at``). Reads of that data
then raise CatalogValuesPrunedError; reads of the version's other rows still
answer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlmodel import Session, col, select

from policyengine_api.data.v2.catalog.parameter_search_file import (
    country_search_file,
    encode_parameter_search_file,
)
from policyengine_api.data.v2.models import (
    Parameter,
    ParameterSearchFile,
    ParameterTreeChild,
    ParameterValue,
    Variable,
)
from policyengine_api.services.v2.metadata.process_state import (
    SelectedCatalogStore,
)
from policyengine_api.services.v2.metadata.types import ParameterTreeLevel
from policyengine_api.services.v2.metadata.validators import (
    CatalogValuesPrunedError,
    MetadataResourceNotFoundError,
    ParameterSearchFileUnavailableError,
    ParameterTreeUnavailableError,
)
from tests.fixtures.v2_catalog import POLICYENGINE_VERSION, normalized_catalog
from tests.fixtures.v2_metadata_service_helpers import (
    catalog_service,
    recorded_statements,
    stored_model_version,
)

pytest_plugins = ("tests.fixtures.v2_metadata_service",)

PRUNED_AT = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
PRUNED_MESSAGE = (
    f"PolicyEngine.py {POLICYENGINE_VERSION}'s current-law parameter values for "
    "us were removed from the catalog, with its parameter tree and search file; "
    f"they return when PolicyEngine.py {POLICYENGINE_VERSION} is installed again"
)
US_CATALOG = normalized_catalog().country("us")
US_VALUE_ID = US_CATALOG.parameters[0].values[0].id


def _add_us_tree_search_file_and_part_variable(session: Session) -> None:
    """Give the US version a tree row, a search file and a variable with parts.

    The variable's adds list comes from the parameter gov.example.rate, so the
    variables catalog carries that parameter's current-law values.
    """
    model_version = stored_model_version(session, "policyengine-us")
    _add_us_tree_row_and_search_file(session)
    session.add(
        Variable(
            id=uuid4(),
            tax_benefit_model_version_id=model_version.id,
            name="total_income",
            label="Total income",
            entity="person",
            default_value=0,
            adds_parameter_path="gov.example.rate",
        )
    )
    session.commit()


def _add_us_tree_row_and_search_file(session: Session) -> None:
    model_version = stored_model_version(session, "policyengine-us")
    encoded = encode_parameter_search_file(country_search_file(US_CATALOG))
    session.add(
        ParameterTreeChild(
            tax_benefit_model_version_id=model_version.id,
            parent_path="",
            path="gov",
            position=0,
            label="Gov",
            child_type="node",
            child_count=1,
        )
    )
    session.add(
        ParameterSearchFile(
            tax_benefit_model_version_id=model_version.id,
            file_format=1,
            compressed_content=encoded.compressed_content,
            content_sha256=encoded.content_sha256,
            uncompressed_size=encoded.uncompressed_size,
            compressed_size=encoded.compressed_size,
        )
    )


def _restore_us_version(session: Session) -> None:
    """Do to the pruned US version what publishing it again does."""
    model_version = stored_model_version(session, "policyengine-us")
    session.add_all(
        ParameterValue(
            id=value.id,
            parameter_id=value.parameter_id,
            value_json=value.value_json,
            start_date=value.start_date,
            end_date=value.end_date,
        )
        for parameter in US_CATALOG.parameters
        for value in parameter.values
    )
    _add_us_tree_row_and_search_file(session)
    model_version.catalog_values_pruned_at = None
    session.add(model_version)
    session.commit()


def _prune_us_version(session: Session) -> None:
    """Do to the stored US version what catalog pruning does."""
    model_version = stored_model_version(session, "policyengine-us")
    version_parameter_ids = select(Parameter.id).where(
        Parameter.tax_benefit_model_version_id == model_version.id
    )
    current_law_values = session.exec(
        select(ParameterValue).where(
            col(ParameterValue.parameter_id).in_(version_parameter_ids),
            col(ParameterValue.policy_id).is_(None),
            col(ParameterValue.dynamic_id).is_(None),
        )
    ).all()
    tree_rows = session.exec(
        select(ParameterTreeChild).where(
            ParameterTreeChild.tax_benefit_model_version_id == model_version.id
        )
    ).all()
    search_files = session.exec(
        select(ParameterSearchFile).where(
            ParameterSearchFile.tax_benefit_model_version_id == model_version.id
        )
    ).all()
    for pruned_row in (*current_law_values, *tree_rows, *search_files):
        session.delete(pruned_row)
    model_version.catalog_values_pruned_at = PRUNED_AT
    session.add(model_version)
    session.commit()


PRUNED_DATA_READS = {
    "parameter values": lambda service: service.list_parameter_values(
        "us", POLICYENGINE_VERSION
    ),
    "one parameter value": lambda service: service.get_parameter_value(
        "us", US_VALUE_ID, POLICYENGINE_VERSION
    ),
    "parameter tree": lambda service: service.list_parameter_children(
        "us", POLICYENGINE_VERSION, level=ParameterTreeLevel()
    ),
    "parameter search file": lambda service: service.get_parameter_search_file(
        "us", POLICYENGINE_VERSION
    ),
    "parameter search file hash": (
        lambda service: service.get_parameter_search_file_hash(
            "us", POLICYENGINE_VERSION
        )
    ),
    "variables catalog": lambda service: service.get_catalog_variables(
        "us", POLICYENGINE_VERSION
    ),
    "parameters catalog": lambda service: service.get_catalog_parameters(
        "us", POLICYENGINE_VERSION, names=["gov.example.rate"]
    ),
}


@pytest.mark.parametrize("read_name", sorted(PRUNED_DATA_READS))
def test_reads_of_pruned_data_name_the_country_and_version(
    catalog_session: Session,
    read_name: str,
) -> None:
    _add_us_tree_search_file_and_part_variable(catalog_session)
    _prune_us_version(catalog_session)

    with pytest.raises(CatalogValuesPrunedError) as raised:
        PRUNED_DATA_READS[read_name](catalog_service(catalog_session))

    assert str(raised.value) == PRUNED_MESSAGE


def test_a_pruned_version_answers_so_even_where_a_read_needs_no_values(
    catalog_session: Session,
) -> None:
    """The version's marker decides, not whether this read needed any values.

    The fixture's variables name no parameter-defined parts, and the requested
    name is not a parameter of the version, so neither read needs values.
    """
    _prune_us_version(catalog_session)
    service = catalog_service(catalog_session)

    with pytest.raises(CatalogValuesPrunedError, match="were removed"):
        service.get_catalog_variables("us", POLICYENGINE_VERSION)
    with pytest.raises(CatalogValuesPrunedError, match="were removed"):
        service.get_catalog_parameters(
            "us", POLICYENGINE_VERSION, names=["gov.example.unknown"]
        )


def test_reads_of_kept_data_still_answer_for_a_pruned_version(
    catalog_session: Session,
) -> None:
    _add_us_tree_search_file_and_part_variable(catalog_session)
    _prune_us_version(catalog_session)
    service = catalog_service(catalog_session)
    parameter_id = US_CATALOG.parameters[0].id

    parameters = service.list_parameters("us", POLICYENGINE_VERSION)
    parameter = service.get_parameter("us", parameter_id, POLICYENGINE_VERSION)
    variables = service.list_variables("us", POLICYENGINE_VERSION)
    model_catalog = service.get_model_catalog("us", POLICYENGINE_VERSION)
    regions = service.list_regions("us", POLICYENGINE_VERSION)
    datasets = service.list_datasets("us", POLICYENGINE_VERSION)
    economy_options = service.get_economy_options("us", POLICYENGINE_VERSION)

    assert [item.name for item in parameters.items] == ["gov.example.rate"]
    assert parameter.item.id == parameter_id
    assert {item.name for item in variables.items} == {
        "employment_income",
        "total_income",
    }
    assert model_catalog.policyengine_version == POLICYENGINE_VERSION
    assert {item.code for item in regions.items} >= {"us"}
    assert datasets.items
    assert economy_options.policyengine_version == POLICYENGINE_VERSION
    # The UK version was not pruned.
    assert len(service.list_parameter_values("uk", POLICYENGINE_VERSION).items) == 2


def test_a_selection_kept_from_before_pruning_reads_the_marker_again(
    catalog_session: Session,
) -> None:
    _add_us_tree_search_file_and_part_variable(catalog_session)
    selected_catalogs = SelectedCatalogStore()
    before = catalog_service(
        catalog_session, selected_catalogs=selected_catalogs
    ).list_parameter_values("us", POLICYENGINE_VERSION)
    # The request's session is done with its rows, so the kept selection holds
    # detached rows, as a closed request session leaves them in production.
    catalog_session.expunge_all()

    _prune_us_version(catalog_session)
    kept_selection = selected_catalogs.get(("us", POLICYENGINE_VERSION))
    service = catalog_service(catalog_session, selected_catalogs=selected_catalogs)

    assert len(before.items) == 2
    assert kept_selection is not None
    assert kept_selection.model_version.catalog_values_pruned_at is None
    for read_name in sorted(PRUNED_DATA_READS):
        with pytest.raises(CatalogValuesPrunedError, match="were removed"):
            PRUNED_DATA_READS[read_name](service)


def test_an_unpruned_version_whose_read_finds_nothing_answers_as_before(
    catalog_session: Session,
) -> None:
    service = catalog_service(catalog_session)

    with pytest.raises(MetadataResourceNotFoundError):
        service.get_parameter_value("us", uuid4(), POLICYENGINE_VERSION)
    with pytest.raises(ParameterTreeUnavailableError):
        service.list_parameter_children("us", POLICYENGINE_VERSION)
    with pytest.raises(ParameterSearchFileUnavailableError):
        service.get_parameter_search_file("us", POLICYENGINE_VERSION)
    with pytest.raises(ParameterSearchFileUnavailableError):
        service.get_parameter_search_file_hash("us", POLICYENGINE_VERSION)
    assert service.list_parameter_values("us", offset=10).items == []
    assert (
        service.get_catalog_parameters("us", names=["gov.example.rate"])
        .parameters[0]
        .values
        != []
    )


def test_a_read_that_finds_rows_does_not_read_the_marker(
    catalog_session: Session,
) -> None:
    service = catalog_service(catalog_session)

    result, statements = recorded_statements(
        catalog_session,
        lambda: service.list_parameter_values("us", POLICYENGINE_VERSION),
    )

    assert len(result.items) == 2
    # The catalog selection and the values read only.
    assert len(statements) == 2
    assert "catalog_values_pruned_at" not in statements[-1]


def _kept_pruned_selection(session: Session) -> SelectedCatalogStore:
    """Return a store holding the US selection made while the version was pruned.

    The request's session is then done with its rows, so the kept selection
    holds detached rows, as a closed request session leaves them in production.
    """
    _add_us_tree_search_file_and_part_variable(session)
    _prune_us_version(session)
    selected_catalogs = SelectedCatalogStore()
    with pytest.raises(CatalogValuesPrunedError):
        catalog_service(
            session, selected_catalogs=selected_catalogs
        ).list_parameter_values("us", POLICYENGINE_VERSION)
    session.expunge_all()
    kept_selection = selected_catalogs.get(("us", POLICYENGINE_VERSION))
    assert kept_selection is not None
    assert kept_selection.model_version.catalog_values_pruned_at is not None
    return selected_catalogs


def test_a_selection_kept_while_pruned_reads_only_the_marker_before_answering(
    catalog_session: Session,
) -> None:
    """A kept pruned selection is checked against the database first.

    The version is still pruned, so the request answers after reading its
    marker alone, without reading the rows pruning removed.
    """
    selected_catalogs = _kept_pruned_selection(catalog_session)
    service = catalog_service(catalog_session, selected_catalogs=selected_catalogs)

    def read_values() -> None:
        with pytest.raises(CatalogValuesPrunedError, match="were removed"):
            service.list_parameter_values("us", POLICYENGINE_VERSION)

    _result, statements = recorded_statements(catalog_session, read_values)

    assert len(statements) == 1
    assert "catalog_values_pruned_at" in statements[0]
    assert "parameter_values" not in statements[0]


def test_a_selection_kept_while_pruned_serves_the_version_once_restored(
    catalog_session: Session,
) -> None:
    """Publishing the version again restores it for a process that kept it pruned.

    The first read after the restoration reads the marker, finds it cleared and
    keeps a new selection, so later reads read neither the marker nor the
    selection again.
    """
    selected_catalogs = _kept_pruned_selection(catalog_session)
    _restore_us_version(catalog_session)
    service = catalog_service(catalog_session, selected_catalogs=selected_catalogs)

    restored = service.list_parameter_values("us", POLICYENGINE_VERSION)
    for read_name in sorted(PRUNED_DATA_READS):
        PRUNED_DATA_READS[read_name](service)
    later, statements = recorded_statements(
        catalog_session,
        lambda: service.list_parameter_values("us", POLICYENGINE_VERSION),
    )

    assert len(restored.items) == 2
    kept_selection = selected_catalogs.get(("us", POLICYENGINE_VERSION))
    assert kept_selection is not None
    assert kept_selection.model_version.catalog_values_pruned_at is None
    assert len(later.items) == 2
    # The values read only.
    assert len(statements) == 1
    assert "catalog_values_pruned_at" not in statements[0]
