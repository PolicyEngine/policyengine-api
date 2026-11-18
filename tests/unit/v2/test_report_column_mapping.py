"""API v1's models leave out the report columns a later revision drops.

The deploy upgrades the database before new code takes traffic, so the release
serving during that upgrade must not name a column it removes. The tables keep
the columns until then: only the models stop selecting and writing them.
"""

import pytest
import sqlalchemy as sa
from sqlmodel import select

from policyengine_api.data.v2.models import (
    V2_METADATA,
    BudgetWindowRun,
    Report,
    ReportRun,
    User,
)

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
def test_a_model_has_no_attribute_for_an_unmapped_column(
    model: type, column_name: str
) -> None:
    assert column_name not in sa.inspect(model).column_attrs
    assert column_name not in model.model_fields
    assert not hasattr(model, column_name)


@pytest.mark.parametrize(("model", "column_name"), UNMAPPED_COLUMNS)
def test_the_table_keeps_an_unmapped_column_until_a_revision_drops_it(
    model: type, column_name: str
) -> None:
    column = V2_METADATA.tables[model.__tablename__].c[column_name]

    assert column.nullable
    assert column.server_default is None


def test_the_reports_user_key_and_index_stay_with_the_column() -> None:
    reports = V2_METADATA.tables["reports"]

    (user_key,) = reports.c.user_id.foreign_keys
    assert user_key.target_fullname == "users.id"
    assert user_key.ondelete == "SET NULL"
    assert "ix_reports_user_id" in {index.name for index in reports.indexes}


def test_reports_and_users_have_no_relationship() -> None:
    assert "user" not in Report.__sqlmodel_relationships__
    assert "reports" not in User.__sqlmodel_relationships__
