"""move dynamic parameters into their own tables

Revision ID: 7f7335f0eb31
Revises: d417fe8b1b17
Create Date: 2026-11-26 00:24:27.129305
Generation: uv run alembic -c alembic-v2.ini revision --autogenerate

Creates dynamic_parameters, with parameters' columns and unique name per
catalog version, and dynamic_parameter_values: a dynamic parameter's
current-law values (no dynamic) and every dynamic's values, with a unique
current-law value per parameter and start date, a unique value per dynamic,
parameter and start date, and the period index. Both are generated.

The data step that follows is hand-written: the user's explicit migration
decision for C1 · 50 (C1 · 46, Q2, 2026-11-25), which the generated-only rule
for revisions requires. Catalog publication can't move rows it already
stored, and dynamics' values aren't catalog data, so the revision moves every
stored version's rows itself, in the one transaction that migrations/v2/env.py
runs every pending revision in:

1. It locks the parameters it moves, so no value can start naming one, and
   refuses, changing nothing, while a policy value names one: deleting the
   parameter would delete that value with it and silently change the policy.
   Operator step C1 · 49 splits such policies first. It also refuses while a
   dynamic's value names a parameter it doesn't move, which the new tables
   can't hold and no reader would find after the move.
2. It copies every version's dynamic parameters, their current-law values and
   every dynamic's values into the new tables, with their IDs and creation
   times, so stored dynamics' content hashes, which cover parameter IDs, stay
   valid.
3. It lowers the child counts of the policy tree rows above the dynamic
   folders and deletes the tree rows of the folders and everything below
   them, so the policy tree shows no empty folder.
4. It deletes the moved values and parameters, and checks that it deleted
   exactly what it copied.

A model's parameters are dynamic by the prefixes of its country, the model
being policyengine-<country>: a frozen copy of the package's
dynamic_parameters.DYNAMIC_PARAMETER_PREFIXES, which a unit test keeps equal
to it; catalog publication compares the installed version's rows with the
package's own classification right after the upgrade.

The downgrade copies both tables back into parameters and parameter_values,
with their IDs, versions published after the upgrade included, then drops
them. It leaves the policy trees as they are, without the dynamic folders
(C1 · 50, decision 1): the parent revision's /v2/policies refuses those
parameters anyway, and publication never compares a stored tree.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.dialects import postgresql

revision: str = "7f7335f0eb31"
down_revision: Union[str, None] = "d417fe8b1b17"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The model assumptions' prefixes by country when this revision was written:
# a frozen copy of dynamic_parameters.DYNAMIC_PARAMETER_PREFIXES.
DYNAMIC_PARAMETER_PREFIXES: dict[str, tuple[str, ...]] = {
    "uk": ("gov.simulation.", "gov.dynamic."),
    "us": ("gov.simulation.", "simulation."),
}

# The columns the data step reads and writes, as lightweight table constructs.
PARAMETER_COLUMNS = (
    "id",
    "created_at",
    "name",
    "label",
    "description",
    "data_type",
    "unit",
    "economy",
    "household",
    "tax_benefit_model_version_id",
)
_models = sa.table("tax_benefit_models", sa.column("id"), sa.column("name"))
_versions = sa.table(
    "tax_benefit_model_versions", sa.column("id"), sa.column("model_id")
)
_parameters = sa.table("parameters", *(sa.column(name) for name in PARAMETER_COLUMNS))
_dynamic_parameters = sa.table(
    "dynamic_parameters", *(sa.column(name) for name in PARAMETER_COLUMNS)
)
_parameter_values = sa.table(
    "parameter_values",
    sa.column("id"),
    sa.column("created_at"),
    sa.column("parameter_id"),
    sa.column("value_json"),
    sa.column("start_date"),
    sa.column("end_date"),
    sa.column("policy_id"),
    sa.column("dynamic_id"),
)
_dynamic_parameter_values = sa.table(
    "dynamic_parameter_values",
    sa.column("id"),
    sa.column("created_at"),
    sa.column("dynamic_parameter_id"),
    sa.column("value_json"),
    sa.column("start_date"),
    sa.column("end_date"),
    sa.column("dynamic_id"),
)
_tree = sa.table(
    "parameter_tree_children",
    sa.column("id"),
    sa.column("tax_benefit_model_version_id"),
    sa.column("parent_path"),
    sa.column("path"),
    sa.column("child_count"),
    sa.column("reform_position"),
    sa.column("reform_child_count"),
)


def _under_dynamic_prefix(
    text: sa.ColumnElement, model_name: sa.ColumnElement
) -> sa.ColumnElement[bool]:
    """Whether ``text`` starts with a prefix of the country of ``model_name``."""
    return sa.or_(
        *(
            sa.and_(
                model_name == f"policyengine-{country_id}",
                sa.or_(*(sa.func.starts_with(text, prefix) for prefix in prefixes)),
            )
            for country_id, prefixes in DYNAMIC_PARAMETER_PREFIXES.items()
        )
    )


def _is_dynamic_path(
    path: sa.ColumnElement, model_name: sa.ColumnElement
) -> sa.ColumnElement[bool]:
    """Whether a tree path is a dynamic folder or below one: path + "." matches."""
    return _under_dynamic_prefix(sa.func.concat(path, "."), model_name)


def _moved_parameter_ids() -> sa.Select:
    """Select the stored parameters that are model assumptions of their country."""
    return (
        sa.select(_parameters.c.id)
        .select_from(
            _parameters.join(
                _versions, _versions.c.id == _parameters.c.tax_benefit_model_version_id
            ).join(_models, _models.c.id == _versions.c.model_id)
        )
        .where(_under_dynamic_prefix(_parameters.c.name, _models.c.name))
    )


def _dynamic_tree_rows() -> sa.Select:
    """Select the tree rows of dynamic folders and everything below them."""
    return (
        sa.select(_tree.c.id)
        .select_from(
            _tree.join(
                _versions, _versions.c.id == _tree.c.tax_benefit_model_version_id
            ).join(_models, _models.c.id == _versions.c.model_id)
        )
        .where(_is_dynamic_path(_tree.c.path, _models.c.name))
    )


def _lower_kept_parents_child_counts(bind: sa.Connection) -> None:
    """Lower each kept tree row's counts by its dynamic children.

    Those are the dynamic folders right below a row that holds policy
    parameters too (``gov``); a top-level folder has no parent row. A child
    with a ``reform_position`` was counted in ``reform_child_count`` too.
    """
    child = _tree.alias("child")
    removed = (
        sa.select(
            child.c.tax_benefit_model_version_id,
            child.c.parent_path,
            sa.func.count().label("children"),
            sa.func.count(child.c.reform_position).label("reform_children"),
        )
        .select_from(
            child.join(
                _versions, _versions.c.id == child.c.tax_benefit_model_version_id
            ).join(_models, _models.c.id == _versions.c.model_id)
        )
        .where(
            _is_dynamic_path(child.c.path, _models.c.name),
            sa.not_(_is_dynamic_path(child.c.parent_path, _models.c.name)),
        )
        .group_by(child.c.tax_benefit_model_version_id, child.c.parent_path)
        .subquery("removed")
    )
    bind.execute(
        sa.update(_tree)
        .where(
            _tree.c.tax_benefit_model_version_id
            == removed.c.tax_benefit_model_version_id,
            _tree.c.path == removed.c.parent_path,
        )
        .values(
            child_count=_tree.c.child_count - removed.c.children,
            reform_child_count=_tree.c.reform_child_count - removed.c.reform_children,
        )
    )


def _move_dynamic_parameters_into_their_tables() -> None:
    """Move every stored dynamic parameter and value, keeping its ID (Q2)."""
    bind = op.get_bind()
    moved_ids = _moved_parameter_ids()
    # Lock the parameters first: inserting a value that names one waits for
    # this transaction, then fails on the deleted parameter, rather than
    # being deleted with it after the count below.
    bind.execute(
        sa.select(_parameters.c.id)
        .where(_parameters.c.id.in_(moved_ids))
        .with_for_update()
    ).all()
    policy_values = bind.execute(
        sa.select(sa.func.count())
        .select_from(_parameter_values)
        .where(
            _parameter_values.c.policy_id.is_not(None),
            _parameter_values.c.parameter_id.in_(moved_ids),
        )
    ).scalar_one()
    if policy_values:
        msg = (
            "the upgrade to 7f7335f0eb31 stopped, changing nothing: policy values "
            f"name dynamic parameters ({policy_values} found), and moving those "
            "parameters out of parameters would delete the values and change the "
            "policies; split those policies into a policy and a dynamic first "
            "(operator step C1 · 49), then upgrade again"
        )
        raise RuntimeError(msg)
    stranded_values = bind.execute(
        sa.select(sa.func.count())
        .select_from(_parameter_values)
        .where(
            _parameter_values.c.dynamic_id.is_not(None),
            _parameter_values.c.parameter_id.not_in(moved_ids),
        )
    ).scalar_one()
    if stranded_values:
        msg = (
            "the upgrade to 7f7335f0eb31 stopped, changing nothing: dynamic values "
            f"name policy parameters ({stranded_values} found), which "
            "dynamic_parameter_values can't hold, so the move would leave them "
            "where no reader finds them; delete or correct them first, then "
            "upgrade again"
        )
        raise RuntimeError(msg)

    # SQLAlchemy keeps an INSERT's row count only when asked to.
    copied_parameters = bind.execute(
        sa.insert(_dynamic_parameters)
        .execution_options(preserve_rowcount=True)
        .from_select(
            PARAMETER_COLUMNS,
            sa.select(*(_parameters.c[name] for name in PARAMETER_COLUMNS)).where(
                _parameters.c.id.in_(moved_ids)
            ),
        )
    ).rowcount
    copied_values = bind.execute(
        sa.insert(_dynamic_parameter_values)
        .execution_options(preserve_rowcount=True)
        .from_select(
            [
                "id",
                "created_at",
                "dynamic_parameter_id",
                "value_json",
                "start_date",
                "end_date",
                "dynamic_id",
            ],
            sa.select(
                _parameter_values.c.id,
                _parameter_values.c.created_at,
                _parameter_values.c.parameter_id,
                _parameter_values.c.value_json,
                _parameter_values.c.start_date,
                _parameter_values.c.end_date,
                _parameter_values.c.dynamic_id,
            ).where(_parameter_values.c.parameter_id.in_(moved_ids)),
        )
    ).rowcount

    _lower_kept_parents_child_counts(bind)
    bind.execute(sa.delete(_tree).where(_tree.c.id.in_(_dynamic_tree_rows())))

    deleted_values = bind.execute(
        sa.delete(_parameter_values).where(
            _parameter_values.c.parameter_id.in_(moved_ids)
        )
    ).rowcount
    deleted_parameters = bind.execute(
        sa.delete(_parameters).where(
            _parameters.c.id.in_(sa.select(_dynamic_parameters.c.id))
        )
    ).rowcount
    if (deleted_parameters, deleted_values) != (copied_parameters, copied_values):
        msg = (
            "the upgrade to 7f7335f0eb31 stopped, changing nothing: it copied "
            f"{copied_parameters} dynamic parameters and {copied_values} values "
            f"but would delete {deleted_parameters} and {deleted_values}"
        )
        raise RuntimeError(msg)


def _move_dynamic_parameters_back() -> None:
    """Copy both tables back into parameters and parameter_values, with their IDs.

    The tree rows the upgrade deleted stay deleted (C1 · 50, decision 1).
    """
    bind = op.get_bind()
    bind.execute(
        sa.insert(_parameters).from_select(
            PARAMETER_COLUMNS,
            sa.select(*(_dynamic_parameters.c[name] for name in PARAMETER_COLUMNS)),
        )
    )
    bind.execute(
        sa.insert(_parameter_values).from_select(
            [
                "id",
                "created_at",
                "parameter_id",
                "value_json",
                "start_date",
                "end_date",
                "policy_id",
                "dynamic_id",
            ],
            sa.select(
                _dynamic_parameter_values.c.id,
                _dynamic_parameter_values.c.created_at,
                _dynamic_parameter_values.c.dynamic_parameter_id,
                _dynamic_parameter_values.c.value_json,
                _dynamic_parameter_values.c.start_date,
                _dynamic_parameter_values.c.end_date,
                sa.null(),
                _dynamic_parameter_values.c.dynamic_id,
            ),
        )
    )


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "dynamic_parameters",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=512), nullable=False),
        sa.Column("label", sqlmodel.sql.sqltypes.AutoString(length=512), nullable=True),
        sa.Column("description", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column(
            "data_type", sqlmodel.sql.sqltypes.AutoString(length=128), nullable=True
        ),
        sa.Column("unit", sqlmodel.sql.sqltypes.AutoString(length=128), nullable=True),
        sa.Column("economy", sa.Boolean(), nullable=True),
        sa.Column("household", sa.Boolean(), nullable=True),
        sa.Column("tax_benefit_model_version_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tax_benefit_model_version_id"],
            ["tax_benefit_model_versions.id"],
            name=op.f(
                "fk_dynamic_parameters_tax_benefit_model_version_id_tax_benefit_model_versions"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dynamic_parameters")),
        sa.UniqueConstraint(
            "tax_benefit_model_version_id",
            "name",
            name="uq_dynamic_parameters_model_version_name",
        ),
    )
    op.create_index(
        op.f("ix_dynamic_parameters_tax_benefit_model_version_id"),
        "dynamic_parameters",
        ["tax_benefit_model_version_id"],
        unique=False,
    )
    op.create_table(
        "dynamic_parameter_values",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("dynamic_parameter_id", sa.Uuid(), nullable=False),
        sa.Column(
            "value_json",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dynamic_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "end_date IS NULL OR end_date >= start_date",
            name=op.f("ck_dynamic_parameter_values_effective_period"),
        ),
        sa.ForeignKeyConstraint(
            ["dynamic_id"],
            ["dynamics.id"],
            name=op.f("fk_dynamic_parameter_values_dynamic_id_dynamics"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dynamic_parameter_id"],
            ["dynamic_parameters.id"],
            name=op.f(
                "fk_dynamic_parameter_values_dynamic_parameter_id_dynamic_parameters"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dynamic_parameter_values")),
    )
    op.create_index(
        "ix_dynamic_parameter_values_parameter_period",
        "dynamic_parameter_values",
        ["dynamic_parameter_id", "start_date", "end_date"],
        unique=False,
    )
    op.create_index(
        "uq_dynamic_parameter_values_current_law_parameter_start_date",
        "dynamic_parameter_values",
        ["dynamic_parameter_id", "start_date"],
        unique=True,
        postgresql_where=sa.text("dynamic_id IS NULL"),
        sqlite_where=sa.text("dynamic_id IS NULL"),
    )
    op.create_index(
        "uq_dynamic_parameter_values_dynamic_parameter_start_date",
        "dynamic_parameter_values",
        ["dynamic_id", "dynamic_parameter_id", "start_date"],
        unique=True,
        postgresql_where=sa.text("dynamic_id IS NOT NULL"),
        sqlite_where=sa.text("dynamic_id IS NOT NULL"),
    )
    # ### end Alembic commands ###
    # Approved hand-written data step (the user's migration decision, C1 · 46,
    # Q2): move every stored dynamic parameter and value into the new tables.
    _move_dynamic_parameters_into_their_tables()


def downgrade() -> None:
    # Approved hand-written data step (the user's migration decision, C1 · 46,
    # Q2): move the rows back before the generated drops delete them.
    _move_dynamic_parameters_back()
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(
        "uq_dynamic_parameter_values_dynamic_parameter_start_date",
        table_name="dynamic_parameter_values",
        postgresql_where=sa.text("dynamic_id IS NOT NULL"),
        sqlite_where=sa.text("dynamic_id IS NOT NULL"),
    )
    op.drop_index(
        "uq_dynamic_parameter_values_current_law_parameter_start_date",
        table_name="dynamic_parameter_values",
        postgresql_where=sa.text("dynamic_id IS NULL"),
        sqlite_where=sa.text("dynamic_id IS NULL"),
    )
    op.drop_index(
        "ix_dynamic_parameter_values_parameter_period",
        table_name="dynamic_parameter_values",
    )
    op.drop_table("dynamic_parameter_values")
    op.drop_index(
        op.f("ix_dynamic_parameters_tax_benefit_model_version_id"),
        table_name="dynamic_parameters",
    )
    op.drop_table("dynamic_parameters")
    # ### end Alembic commands ###
