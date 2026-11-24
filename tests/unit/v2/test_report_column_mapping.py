"""API v1's models leave out the report columns a later revision drops.

The deploy upgrades the database before new code takes traffic, so the release
serving during that upgrade must not name a column it removes. The tables keep
the columns until then: each stays a SQLModel field, as rule
``api.data.orm-only`` requires of every column, and ``exclude_properties``
leaves it out of the mapper, so the models neither select nor write it.
"""

import pytest
import sqlalchemy as sa
from pydantic_core import PydanticUndefined
from sqlmodel import select

from policyengine_api.data.v2.models import (
    BudgetWindowRun,
    Report,
    ReportRun,
    User,
)
from tests.unit.v2.v2_schema_reading import model_columns, stored_v2_table

UNMAPPED_COLUMNS = [
    (Report, "label"),
    (Report, "description"),
    (Report, "user_id"),
    (ReportRun, "trigger"),
    (BudgetWindowRun, "trigger"),
]


@pytest.mark.parametrize(("model", "column_name"), UNMAPPED_COLUMNS)
def test_a_whole_row_read_names_no_unmapped_column(
    model: type, column_name: str
) -> None:
    selected_names = {column.name for column in select(model).selected_columns}

    assert column_name not in selected_names


@pytest.mark.parametrize(("model", "column_name"), UNMAPPED_COLUMNS)
def test_the_mapper_leaves_out_an_unmapped_column(
    model: type, column_name: str
) -> None:
    mapper = sa.inspect(model)

    assert column_name in mapper.exclude_properties
    assert column_name not in mapper.column_attrs


@pytest.mark.parametrize(("model", "column_name"), UNMAPPED_COLUMNS)
def test_the_table_keeps_an_unmapped_column_until_a_revision_drops_it(
    model: type, column_name: str
) -> None:
    stored_column = stored_v2_table(model.__tablename__).columns[column_name]
    field = model.model_fields[column_name]
    column_arguments = getattr(field, "sa_column_kwargs", None)

    assert stored_column.nullable
    assert field.default is None
    assert column_arguments in (None, PydanticUndefined)


@pytest.mark.parametrize("model", [ReportRun, BudgetWindowRun])
def test_a_runs_trigger_keeps_the_type_users_run_records_share(model: type) -> None:
    trigger_type = model.model_fields["trigger"].sa_type
    record_trigger_type = model_columns("user_report_run_associations").trigger.type

    assert isinstance(trigger_type, sa.Enum)
    assert isinstance(record_trigger_type, sa.Enum)
    assert trigger_type.name == record_trigger_type.name == "v2_report_run_trigger"
    assert trigger_type.enums == record_trigger_type.enums


def test_the_reports_user_key_and_index_stay_with_the_column() -> None:
    reports = stored_v2_table("reports")

    (user_key,) = (
        foreign_key
        for foreign_key in reports.foreign_keys
        if foreign_key.columns == ("user_id",)
    )
    assert user_key.targets == ("users.id",)
    assert user_key.ondelete == "SET NULL"
    assert reports.index_columns["ix_reports_user_id"] == ("user_id",)


def test_reports_and_users_have_no_relationship() -> None:
    assert "user" not in Report.__sqlmodel_relationships__
    assert "reports" not in User.__sqlmodel_relationships__
