"""Check the revision that moves dynamic parameters into their own tables.

Revision 7f7335f0eb31 creates ``dynamic_parameters`` and
``dynamic_parameter_values``, then moves every stored version's dynamic
parameters (US ``gov.simulation.`` and ``simulation.``, UK ``gov.simulation.``
and ``gov.dynamic.``), their current-law values and every dynamic's values
there with their IDs, deletes the policy tree's rows under those folders,
lowering their parents' child counts, and deletes the originals. It refuses
to run while a policy value names a parameter it would move. Its downgrade
moves the rows back and leaves the trees as they are (C1 · 46, Q2; C1 · 50's
decision 1).

The rows are written as the disposable database's owner. A country's
parameters are those of model ``policyengine-<country>``, so the tests store
their own versions of those models, and look only at those versions' rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from policyengine_api.data.v2.dynamic_parameter_move_qualification import (
    count_policy_values_naming_dynamic_parameters,
    dynamic_parameter_move_is_pending,
)
from sqlalchemy import delete, select, update
from sqlmodel import col

from policyengine_api.data.v2.models import (
    Dynamic,
    DynamicParameter,
    DynamicParameterValue,
    Parameter,
    ParameterTreeChild,
    ParameterValue,
    Policy,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)
from tests.fixtures.database_sessions import schema_inspector
from tests.fixtures.integration.alembic_v2 import alembic_v2_config
from tests.integration.alembic_version_rows import current_revision
from tests.integration.simulation_rows import add_row, refused

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

PARENT_REVISION = "d417fe8b1b17"
DYNAMIC_PARAMETER_TABLES_REVISION = "7f7335f0eb31"
NEW_TABLES = frozenset({"dynamic_parameters", "dynamic_parameter_values"})
START_2026 = datetime(2026, 1, 1, tzinfo=UTC)
START_2027 = datetime(2027, 1, 1, tzinfo=UTC)

US_POLICY_PARAMETER = "gov.irs.rate"
# Not a US prefix: only the UK's gov.dynamic. holds model assumptions.
US_GOV_DYNAMIC_POLICY_PARAMETER = "gov.dynamic.example"
US_ELASTICITY = "gov.simulation.labor_supply_responses.elasticity"
US_MTR_DELTA = "simulation.marginal_tax_rate_delta"
UK_POLICY_PARAMETER = "gov.hmrc.rate"
# Not a UK prefix: only the US's top-level simulation. holds model assumptions.
UK_SIMULATION_POLICY_PARAMETER = "simulation.example"
UK_ELASTICITY = "gov.simulation.income_elasticity"
UK_OBR_SWITCH = "gov.dynamic.obr_labour_supply_assumptions"

POLICY_PARAMETERS = {
    "us": (US_POLICY_PARAMETER, US_GOV_DYNAMIC_POLICY_PARAMETER),
    "uk": (UK_POLICY_PARAMETER, UK_SIMULATION_POLICY_PARAMETER),
}
DYNAMIC_PARAMETERS = {
    "us": (US_ELASTICITY, US_MTR_DELTA),
    "uk": (UK_ELASTICITY, UK_OBR_SWITCH),
}


@dataclass(frozen=True)
class TreeRow:
    """One ``parameter_tree_children`` row a test writes, by its path."""

    parent_path: str
    path: str
    position: int
    child_count: int | None = None
    reform_position: int | None = None
    reform_child_count: int | None = None

    @property
    def is_parameter(self) -> bool:
        return self.child_count is None


# Each country's tree before the revision. "gov" has three folders; the US
# top-level "simulation" folder has no parent row. The UK's gov.dynamic is not
# reform-changeable (no reform position), so the UK's "gov" loses one of its
# two reform children.
TREES = {
    "us": (
        TreeRow("", "gov", 0, child_count=3, reform_position=0, reform_child_count=3),
        TreeRow("", "simulation", 1, child_count=1, reform_child_count=0),
        TreeRow(
            "gov",
            "gov.dynamic",
            0,
            child_count=1,
            reform_position=0,
            reform_child_count=1,
        ),
        TreeRow("gov.dynamic", US_GOV_DYNAMIC_POLICY_PARAMETER, 0, reform_position=0),
        TreeRow(
            "gov", "gov.irs", 1, child_count=1, reform_position=1, reform_child_count=1
        ),
        TreeRow("gov.irs", US_POLICY_PARAMETER, 0, reform_position=0),
        TreeRow(
            "gov",
            "gov.simulation",
            2,
            child_count=1,
            reform_position=2,
            reform_child_count=1,
        ),
        TreeRow(
            "gov.simulation",
            "gov.simulation.labor_supply_responses",
            0,
            child_count=1,
            reform_position=0,
            reform_child_count=1,
        ),
        TreeRow(
            "gov.simulation.labor_supply_responses", US_ELASTICITY, 0, reform_position=0
        ),
        TreeRow("simulation", US_MTR_DELTA, 0),
    ),
    "uk": (
        TreeRow("", "gov", 0, child_count=3, reform_position=0, reform_child_count=2),
        TreeRow("", "simulation", 1, child_count=1, reform_child_count=0),
        TreeRow("gov", "gov.dynamic", 0, child_count=1, reform_child_count=0),
        TreeRow("gov.dynamic", UK_OBR_SWITCH, 0),
        TreeRow(
            "gov", "gov.hmrc", 1, child_count=1, reform_position=0, reform_child_count=1
        ),
        TreeRow("gov.hmrc", UK_POLICY_PARAMETER, 0, reform_position=0),
        TreeRow(
            "gov",
            "gov.simulation",
            2,
            child_count=1,
            reform_position=1,
            reform_child_count=1,
        ),
        TreeRow("gov.simulation", UK_ELASTICITY, 0, reform_position=0),
        TreeRow("simulation", UK_SIMULATION_POLICY_PARAMETER, 0),
    ),
}
# What the revision leaves of each tree: no dynamic folder, and "gov" counts
# only the folders it keeps.
TREES_AFTER_THE_MOVE = {
    "us": {
        "gov": (2, 2),
        "gov.dynamic": (1, 1),
        US_GOV_DYNAMIC_POLICY_PARAMETER: (None, None),
        "gov.irs": (1, 1),
        US_POLICY_PARAMETER: (None, None),
    },
    "uk": {
        "gov": (1, 1),
        "gov.hmrc": (1, 1),
        UK_POLICY_PARAMETER: (None, None),
        "simulation": (1, 0),
        UK_SIMULATION_POLICY_PARAMETER: (None, None),
    },
}


@dataclass
class StoredCountry:
    """One country's catalog version the test stored, and what names it."""

    country_id: str
    model_id: UUID
    model_created: bool
    version_id: UUID
    parameter_ids: dict[str, UUID] = field(default_factory=dict)
    dynamic_id: UUID | None = None
    policy_ids: list[UUID] = field(default_factory=list)


@pytest.fixture
def sessions(
    v2_owner_sessions: sessionmaker[Session],
) -> Iterator[sessionmaker[Session]]:
    """Yield the owner's Session factories on a database at head; leave it at head.

    ``v2_owner_sessions`` checks that the target is the disposable database
    before this migrates it.
    """
    command.upgrade(alembic_v2_config(), "head")
    try:
        yield v2_owner_sessions
    finally:
        command.upgrade(alembic_v2_config(), "head")


def _model_id(session: Session, country_id: str) -> tuple[UUID, bool]:
    """Return the country's model, storing it first if it isn't stored."""
    name = f"policyengine-{country_id}"
    stored = session.scalars(
        select(col(TaxBenefitModel.id)).where(col(TaxBenefitModel.name) == name)
    ).one_or_none()
    if stored is not None:
        return stored, False
    model_id = uuid4()
    add_row(session, TaxBenefitModel, id=model_id, name=name)
    return model_id, True


def _store_country(session: Session, country_id: str) -> StoredCountry:
    """Store a catalog version with policy and dynamic parameters and a tree.

    Every parameter has one current-law value from 2026; a dynamic sets each
    dynamic parameter from 2027, and a policy sets each policy parameter.
    """
    model_id, model_created = _model_id(session, country_id)
    stored = StoredCountry(
        country_id=country_id,
        model_id=model_id,
        model_created=model_created,
        version_id=uuid4(),
    )
    add_row(
        session,
        TaxBenefitModelVersion,
        id=stored.version_id,
        model_id=model_id,
        version=f"c1-50-{stored.version_id.hex[:12]}",
        current_law_id=1,
        metadata_time_periods=[2026],
        catalog_format=2,
    )
    for name in (*POLICY_PARAMETERS[country_id], *DYNAMIC_PARAMETERS[country_id]):
        parameter_id = uuid4()
        stored.parameter_ids[name] = parameter_id
        add_row(
            session,
            Parameter,
            id=parameter_id,
            name=name,
            label=f"Label of {name}",
            description=f"Description of {name}",
            data_type="float",
            unit="/1",
            economy=True,
            household=name != UK_OBR_SWITCH,
            tax_benefit_model_version_id=stored.version_id,
        )
        add_row(
            session,
            ParameterValue,
            id=uuid4(),
            parameter_id=parameter_id,
            value_json=0.5,
            start_date=START_2026,
        )
    stored.dynamic_id = uuid4()
    add_row(
        session,
        Dynamic,
        id=stored.dynamic_id,
        country_id=country_id,
        tax_benefit_model_id=model_id,
        tax_benefit_model_version_id=stored.version_id,
        canonicalization_version=1,
        content_hash=uuid4().hex * 2,
    )
    for name in DYNAMIC_PARAMETERS[country_id]:
        add_row(
            session,
            ParameterValue,
            id=uuid4(),
            parameter_id=stored.parameter_ids[name],
            dynamic_id=stored.dynamic_id,
            value_json={"set": name},
            start_date=START_2027,
            end_date=datetime(2027, 12, 31, tzinfo=UTC),
        )
    policy_id = _store_policy(session, stored)
    for name in POLICY_PARAMETERS[country_id]:
        _store_policy_value(session, stored, policy_id, name)
    for row in TREES[country_id]:
        add_row(
            session,
            ParameterTreeChild,
            id=uuid4(),
            tax_benefit_model_version_id=stored.version_id,
            parent_path=row.parent_path,
            path=row.path,
            position=row.position,
            label=row.path,
            child_type="parameter" if row.is_parameter else "node",
            child_count=row.child_count,
            reform_position=row.reform_position,
            reform_child_count=row.reform_child_count,
            parameter_id=stored.parameter_ids[row.path] if row.is_parameter else None,
            economy=True if row.is_parameter else None,
            household=True if row.is_parameter else None,
        )
    return stored


def _store_policy(session: Session, stored: StoredCountry) -> UUID:
    policy_id = uuid4()
    add_row(
        session,
        Policy,
        id=policy_id,
        country_id=stored.country_id,
        tax_benefit_model_id=stored.model_id,
        tax_benefit_model_version_id=stored.version_id,
        canonicalization_version=1,
        content_hash=uuid4().hex * 2,
    )
    stored.policy_ids.append(policy_id)
    return policy_id


def _store_policy_value(
    session: Session, stored: StoredCountry, policy_id: UUID, parameter_name: str
) -> None:
    add_row(
        session,
        ParameterValue,
        id=uuid4(),
        parameter_id=stored.parameter_ids[parameter_name],
        policy_id=policy_id,
        value_json=0.25,
        start_date=START_2026,
    )


def _remove(sessions: sessionmaker[Session], countries: list[StoredCountry]) -> None:
    """Delete what the test stored; a version's deletion takes its catalog rows."""
    with sessions.begin() as session:
        for stored in countries:
            session.execute(delete(Policy).where(col(Policy.id).in_(stored.policy_ids)))
            session.execute(delete(Dynamic).where(col(Dynamic.id) == stored.dynamic_id))
            session.execute(
                delete(TaxBenefitModelVersion).where(
                    col(TaxBenefitModelVersion.id) == stored.version_id
                )
            )
            if stored.model_created:
                session.execute(
                    delete(TaxBenefitModel).where(
                        col(TaxBenefitModel.id) == stored.model_id
                    )
                )


@pytest.fixture
def stored_countries(
    sessions: sessionmaker[Session],
) -> Iterator[list[StoredCountry]]:
    """Store a US and a UK catalog version at the parent revision; remove them."""
    command.downgrade(alembic_v2_config(), PARENT_REVISION)
    countries: list[StoredCountry] = []
    try:
        with sessions.begin() as session:
            countries.extend(
                _store_country(session, country_id) for country_id in ("us", "uk")
            )
        yield countries
    finally:
        command.upgrade(alembic_v2_config(), "head")
        _remove(sessions, countries)


def _version_ids(countries: list[StoredCountry]) -> list[UUID]:
    return [stored.version_id for stored in countries]


def _parameter_rows(session: Session, model: Any, version_ids: list[UUID]) -> set:
    """Return a parameter table's rows of the given versions, every column."""
    return {
        (
            row.id,
            row.created_at,
            row.name,
            row.label,
            row.description,
            row.data_type,
            row.unit,
            row.economy,
            row.household,
            row.tax_benefit_model_version_id,
        )
        for row in session.scalars(
            select(model).where(
                col(model.tax_benefit_model_version_id).in_(version_ids)
            )
        )
    }


def _parameter_value_rows(session: Session, version_ids: list[UUID]) -> set:
    """Return ``parameter_values`` rows of the versions' parameters."""
    return {
        (
            row.id,
            row.created_at,
            row.parameter_id,
            repr(row.value_json),
            row.start_date,
            row.end_date,
            row.policy_id,
            row.dynamic_id,
        )
        for row in session.scalars(
            select(ParameterValue)
            .join(Parameter, col(Parameter.id) == col(ParameterValue.parameter_id))
            .where(col(Parameter.tax_benefit_model_version_id).in_(version_ids))
        )
    }


def _dynamic_parameter_value_rows(session: Session, version_ids: list[UUID]) -> set:
    """Return ``dynamic_parameter_values`` rows in ``_parameter_value_rows``' shape.

    The policy column, which the table lacks, is None.
    """
    return {
        (
            row.id,
            row.created_at,
            row.dynamic_parameter_id,
            repr(row.value_json),
            row.start_date,
            row.end_date,
            None,
            row.dynamic_id,
        )
        for row in session.scalars(
            select(DynamicParameterValue)
            .join(
                DynamicParameter,
                col(DynamicParameter.id)
                == col(DynamicParameterValue.dynamic_parameter_id),
            )
            .where(col(DynamicParameter.tax_benefit_model_version_id).in_(version_ids))
        )
    }


def _tree_rows(session: Session, version_ids: list[UUID]) -> set:
    return {
        (
            row.id,
            row.tax_benefit_model_version_id,
            row.parent_path,
            row.path,
            row.position,
            row.label,
            row.child_type,
            row.child_count,
            row.reform_position,
            row.reform_child_count,
            row.parameter_id,
        )
        for row in session.scalars(
            select(ParameterTreeChild).where(
                col(ParameterTreeChild.tax_benefit_model_version_id).in_(version_ids)
            )
        )
    }


@dataclass(frozen=True)
class CatalogSnapshot:
    """The stored versions' catalog rows, per table.

    The new tables' rows are None when the tables don't exist.
    """

    parameters: set
    parameter_values: set
    tree: set
    dynamic_parameters: set | None
    dynamic_parameter_values: set | None


def _snapshot(
    sessions: sessionmaker[Session], countries: list[StoredCountry]
) -> CatalogSnapshot:
    version_ids = _version_ids(countries)
    with sessions() as session:
        moved = schema_inspector(session).has_table("dynamic_parameters")
        return CatalogSnapshot(
            parameters=_parameter_rows(session, Parameter, version_ids),
            parameter_values=_parameter_value_rows(session, version_ids),
            tree=_tree_rows(session, version_ids),
            dynamic_parameters=(
                _parameter_rows(session, DynamicParameter, version_ids)
                if moved
                else None
            ),
            dynamic_parameter_values=(
                _dynamic_parameter_value_rows(session, version_ids) if moved else None
            ),
        )


def _is_dynamic(country: StoredCountry, parameter_id: UUID) -> bool:
    return parameter_id in {
        country.parameter_ids[name] for name in DYNAMIC_PARAMETERS[country.country_id]
    }


def _dynamic_parameter_ids(countries: list[StoredCountry]) -> set[UUID]:
    return {
        stored.parameter_ids[name]
        for stored in countries
        for name in DYNAMIC_PARAMETERS[stored.country_id]
    }


def _tree_counts(snapshot: CatalogSnapshot, version_id: UUID) -> dict:
    return {row[3]: (row[7], row[9]) for row in snapshot.tree if row[1] == version_id}


def test_the_revision_adds_only_the_two_tables(
    sessions: sessionmaker[Session],
) -> None:
    config = alembic_v2_config()
    command.downgrade(config, PARENT_REVISION)
    with sessions() as session:
        inspector = schema_inspector(session)
        before = {
            table: (inspector.get_columns(table), inspector.get_indexes(table))
            for table in inspector.get_table_names()
        }
    command.upgrade(config, DYNAMIC_PARAMETER_TABLES_REVISION)
    with sessions() as session:
        inspector = schema_inspector(session)
        tables = set(inspector.get_table_names())
        assert tables - set(before) == NEW_TABLES
        for table, (columns, indexes) in before.items():
            assert inspector.get_columns(table) == columns, table
            assert inspector.get_indexes(table) == indexes, table
        parameter_columns = {
            column["name"]: (str(column["type"]), column["nullable"])
            for column in inspector.get_columns("parameters")
        }
        assert {
            column["name"]: (str(column["type"]), column["nullable"])
            for column in inspector.get_columns("dynamic_parameters")
        } == parameter_columns
        assert {
            column["name"]: (str(column["type"]), column["nullable"])
            for column in inspector.get_columns("dynamic_parameter_values")
        } == {
            "id": ("UUID", False),
            "created_at": ("TIMESTAMP", False),
            "dynamic_parameter_id": ("UUID", False),
            "value_json": ("JSONB", False),
            "start_date": ("TIMESTAMP", False),
            "end_date": ("TIMESTAMP", True),
            "dynamic_id": ("UUID", True),
        }
        assert {
            (
                tuple(key["constrained_columns"]),
                key["referred_table"],
                key["options"].get("ondelete"),
            )
            for key in inspector.get_foreign_keys("dynamic_parameter_values")
        } == {
            (("dynamic_parameter_id",), "dynamic_parameters", "CASCADE"),
            (("dynamic_id",), "dynamics", "CASCADE"),
        }
        assert {
            (
                tuple(key["constrained_columns"]),
                key["referred_table"],
                key["options"].get("ondelete"),
            )
            for key in inspector.get_foreign_keys("dynamic_parameters")
        } == {
            (
                ("tax_benefit_model_version_id",),
                "tax_benefit_model_versions",
                "CASCADE",
            )
        }
        assert {
            (
                index["name"],
                tuple(index["column_names"]),
                bool(index["unique"]),
                str(index.get("dialect_options", {}).get("postgresql_where")),
            )
            for index in inspector.get_indexes("dynamic_parameter_values")
        } == {
            (
                "ix_dynamic_parameter_values_parameter_period",
                ("dynamic_parameter_id", "start_date", "end_date"),
                False,
                "None",
            ),
            (
                "uq_dynamic_parameter_values_current_law_parameter_start_date",
                ("dynamic_parameter_id", "start_date"),
                True,
                "(dynamic_id IS NULL)",
            ),
            (
                "uq_dynamic_parameter_values_dynamic_parameter_start_date",
                ("dynamic_id", "dynamic_parameter_id", "start_date"),
                True,
                "(dynamic_id IS NOT NULL)",
            ),
        }
        assert {
            constraint["name"]: tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints("dynamic_parameters")
        } == {
            "uq_dynamic_parameters_model_version_name": (
                "tax_benefit_model_version_id",
                "name",
            )
        }
        assert {
            check["name"]
            for check in inspector.get_check_constraints("dynamic_parameter_values")
        } == {"ck_dynamic_parameter_values_effective_period"}

    command.downgrade(config, PARENT_REVISION)
    with sessions() as session:
        assert set(schema_inspector(session).get_table_names()) == set(before)
    command.upgrade(config, "head")
    command.check(config)


def test_the_upgrade_moves_every_dynamic_parameter_and_value_with_its_id(
    sessions: sessionmaker[Session], stored_countries: list[StoredCountry]
) -> None:
    config = alembic_v2_config()
    before = _snapshot(sessions, stored_countries)
    dynamic_ids = _dynamic_parameter_ids(stored_countries)

    command.upgrade(config, DYNAMIC_PARAMETER_TABLES_REVISION)
    moved = _snapshot(sessions, stored_countries)

    assert {row[0] for row in before.parameters} - dynamic_ids == {
        row[0] for row in moved.parameters
    }
    assert moved.dynamic_parameters == {
        row for row in before.parameters if row[0] in dynamic_ids
    }
    assert moved.parameters == {
        row for row in before.parameters if row[0] not in dynamic_ids
    }
    # Current-law values and the dynamics' values move, with their IDs and
    # creation times; the policies' values and the policy parameters'
    # current-law values stay.
    assert moved.dynamic_parameter_values == {
        row for row in before.parameter_values if row[2] in dynamic_ids
    }
    assert moved.parameter_values == {
        row for row in before.parameter_values if row[2] not in dynamic_ids
    }
    assert {row[7] for row in moved.dynamic_parameter_values} == {
        None,
        *(stored.dynamic_id for stored in stored_countries),
    }
    assert all(row[7] is None for row in moved.parameter_values)
    for stored in stored_countries:
        assert (
            _tree_counts(moved, stored.version_id)
            == (TREES_AFTER_THE_MOVE[stored.country_id])
        )
    # The kept rows are unchanged apart from "gov"'s counts.
    assert {row for row in moved.tree if row[3] != "gov"} <= before.tree


def test_the_downgrade_moves_them_back_and_leaves_the_trees(
    sessions: sessionmaker[Session], stored_countries: list[StoredCountry]
) -> None:
    config = alembic_v2_config()
    before = _snapshot(sessions, stored_countries)
    command.upgrade(config, DYNAMIC_PARAMETER_TABLES_REVISION)
    moved = _snapshot(sessions, stored_countries)
    # A version published after the upgrade has its dynamic parameters in the
    # new table only; the downgrade moves them too.
    later = stored_countries[0]
    later_parameter_id = uuid4()
    later_value_id = uuid4()
    with sessions.begin() as session:
        add_row(
            session,
            DynamicParameter,
            id=later_parameter_id,
            name="gov.simulation.published_after_the_move",
            tax_benefit_model_version_id=later.version_id,
        )
        add_row(
            session,
            DynamicParameterValue,
            id=later_value_id,
            dynamic_parameter_id=later_parameter_id,
            value_json=1,
            start_date=START_2026,
        )

    command.downgrade(config, PARENT_REVISION)
    downgraded = _snapshot(sessions, stored_countries)

    assert downgraded.dynamic_parameters is None
    assert downgraded.dynamic_parameter_values is None
    assert {row for row in downgraded.parameters if row[0] != later_parameter_id} == (
        before.parameters
    )
    assert {row[0] for row in downgraded.parameters} >= {later_parameter_id}
    assert {
        row for row in downgraded.parameter_values if row[0] != later_value_id
    } == before.parameter_values
    assert {
        (row[2], row[6], row[7])
        for row in downgraded.parameter_values
        if row[0] == later_value_id
    } == {(later_parameter_id, None, None)}
    # Decision 1: the trees stay as the upgrade left them.
    assert downgraded.tree == moved.tree

    command.upgrade(config, DYNAMIC_PARAMETER_TABLES_REVISION)
    upgraded_again = _snapshot(sessions, stored_countries)
    assert upgraded_again.parameters == moved.parameters
    assert upgraded_again.parameter_values == moved.parameter_values
    assert upgraded_again.tree == moved.tree
    assert upgraded_again.dynamic_parameters is not None
    assert {
        row for row in upgraded_again.dynamic_parameters if row[0] != later_parameter_id
    } == moved.dynamic_parameters
    assert upgraded_again.dynamic_parameter_values is not None
    assert {
        row
        for row in upgraded_again.dynamic_parameter_values
        if row[0] != later_value_id
    } == moved.dynamic_parameter_values


@pytest.mark.parametrize(
    ("country_id", "parameter_name"),
    [("us", US_MTR_DELTA), ("us", US_ELASTICITY), ("uk", UK_OBR_SWITCH)],
)
def test_the_upgrade_refuses_while_a_policy_value_names_a_dynamic_parameter(
    sessions: sessionmaker[Session],
    stored_countries: list[StoredCountry],
    country_id: str,
    parameter_name: str,
) -> None:
    config = alembic_v2_config()
    (stored,) = (item for item in stored_countries if item.country_id == country_id)
    with sessions.begin() as session:
        policy_id = _store_policy(session, stored)
        _store_policy_value(session, stored, policy_id, parameter_name)
    before = _snapshot(sessions, stored_countries)

    with pytest.raises(RuntimeError, match="policy values name dynamic parameters"):
        command.upgrade(config, DYNAMIC_PARAMETER_TABLES_REVISION)

    assert current_revision(sessions) == PARENT_REVISION
    assert _snapshot(sessions, stored_countries) == before
    with sessions() as session:
        assert not NEW_TABLES & set(schema_inspector(session).get_table_names())
    # Once the policy no longer sets it, as after C1 · 49's split, the upgrade runs.
    with sessions.begin() as session:
        session.execute(delete(Policy).where(col(Policy.id) == policy_id))
    stored.policy_ids.remove(policy_id)
    command.upgrade(config, DYNAMIC_PARAMETER_TABLES_REVISION)
    assert current_revision(sessions) == DYNAMIC_PARAMETER_TABLES_REVISION


def test_policy_values_on_another_country_s_prefix_stay_and_don_t_refuse(
    sessions: sessionmaker[Session], stored_countries: list[StoredCountry]
) -> None:
    """A US ``gov.dynamic.`` or UK ``simulation.`` parameter is a policy parameter."""
    config = alembic_v2_config()
    before = _snapshot(sessions, stored_countries)

    command.upgrade(config, DYNAMIC_PARAMETER_TABLES_REVISION)

    moved = _snapshot(sessions, stored_countries)
    kept_names = {row[2] for row in moved.parameters}
    assert {US_GOV_DYNAMIC_POLICY_PARAMETER, UK_SIMULATION_POLICY_PARAMETER} <= (
        kept_names
    )
    policy_values = {row for row in before.parameter_values if row[6] is not None}
    assert policy_values <= moved.parameter_values


def test_the_new_tables_keep_one_value_per_owner_parameter_and_date(
    sessions: sessionmaker[Session], stored_countries: list[StoredCountry]
) -> None:
    command.upgrade(alembic_v2_config(), "head")
    stored = stored_countries[0]
    elasticity_id = stored.parameter_ids[US_ELASTICITY]
    with sessions() as session:
        current_law = {
            "dynamic_parameter_id": elasticity_id,
            "value_json": 0.5,
            "start_date": START_2026,
        }
        with refused(
            session,
            match="uq_dynamic_parameter_values_current_law_parameter_start_date",
        ):
            add_row(session, DynamicParameterValue, id=uuid4(), **current_law)
        dynamic_value = {**current_law, "dynamic_id": stored.dynamic_id}
        add_row(session, DynamicParameterValue, id=uuid4(), **dynamic_value)
        with refused(
            session, match="uq_dynamic_parameter_values_dynamic_parameter_start_date"
        ):
            add_row(session, DynamicParameterValue, id=uuid4(), **dynamic_value)
        with refused(session, match="ck_dynamic_parameter_values_effective_period"):
            add_row(
                session,
                DynamicParameterValue,
                id=uuid4(),
                **{**current_law, "start_date": START_2027},
                end_date=START_2026,
            )
        with refused(session, match="uq_dynamic_parameters_model_version_name"):
            add_row(
                session,
                DynamicParameter,
                id=uuid4(),
                name=US_ELASTICITY,
                tax_benefit_model_version_id=stored.version_id,
            )
        session.rollback()


def test_a_dynamic_s_values_go_with_it_and_a_parameter_s_with_the_parameter(
    sessions: sessionmaker[Session], stored_countries: list[StoredCountry]
) -> None:
    command.upgrade(alembic_v2_config(), "head")
    us, uk = stored_countries
    with sessions.begin() as session:
        session.execute(delete(Dynamic).where(col(Dynamic.id) == us.dynamic_id))
        session.execute(
            delete(DynamicParameter).where(
                col(DynamicParameter.id) == uk.parameter_ids[UK_OBR_SWITCH]
            )
        )
    with sessions() as session:
        remaining = {
            (row.dynamic_parameter_id, row.dynamic_id)
            for row in session.scalars(
                select(DynamicParameterValue).where(
                    col(DynamicParameterValue.dynamic_parameter_id).in_(
                        _dynamic_parameter_ids(stored_countries)
                    )
                )
            )
        }
    assert remaining == {
        (us.parameter_ids[US_ELASTICITY], None),
        (us.parameter_ids[US_MTR_DELTA], None),
        (uk.parameter_ids[UK_ELASTICITY], None),
        (uk.parameter_ids[UK_ELASTICITY], uk.dynamic_id),
    }
    us.dynamic_id = None


def test_tree_counts_lower_only_for_kept_parents(
    sessions: sessionmaker[Session], stored_countries: list[StoredCountry]
) -> None:
    """A parent row the revision deletes itself has nothing to lower."""
    with sessions.begin() as session:
        session.execute(
            update(ParameterTreeChild)
            .where(
                col(ParameterTreeChild.tax_benefit_model_version_id)
                == stored_countries[0].version_id,
                col(ParameterTreeChild.path) == "gov.simulation",
            )
            .values(child_count=7)
        )
    command.upgrade(alembic_v2_config(), DYNAMIC_PARAMETER_TABLES_REVISION)
    moved = _snapshot(sessions, stored_countries)
    assert (
        _tree_counts(moved, stored_countries[0].version_id)
        == (TREES_AFTER_THE_MOVE["us"])
    )


def test_the_seed_workflow_s_check_counts_what_the_revision_refuses(
    sessions: sessionmaker[Session], stored_countries: list[StoredCountry]
) -> None:
    """The read-only step and the revision find the same policy values.

    Values on another country's prefix (a US ``gov.dynamic.`` or UK
    ``simulation.`` parameter) count for neither.
    """
    with sessions() as session:
        assert dynamic_parameter_move_is_pending(session)
        before = count_policy_values_naming_dynamic_parameters(session)
    us, uk = stored_countries
    with sessions.begin() as session:
        us_policy = _store_policy(session, us)
        _store_policy_value(session, us, us_policy, US_MTR_DELTA)
        _store_policy_value(session, us, us_policy, US_ELASTICITY)
        uk_policy = _store_policy(session, uk)
        _store_policy_value(session, uk, uk_policy, UK_OBR_SWITCH)

    with sessions() as session:
        assert count_policy_values_naming_dynamic_parameters(session) == before + 3
    with pytest.raises(RuntimeError, match="policy values name dynamic parameters"):
        command.upgrade(alembic_v2_config(), DYNAMIC_PARAMETER_TABLES_REVISION)

    with sessions.begin() as session:
        session.execute(
            delete(Policy).where(col(Policy.id).in_([us_policy, uk_policy]))
        )
    us.policy_ids.remove(us_policy)
    uk.policy_ids.remove(uk_policy)
    with sessions() as session:
        assert count_policy_values_naming_dynamic_parameters(session) == before
    command.upgrade(alembic_v2_config(), "head")
    with sessions() as session:
        assert not dynamic_parameter_move_is_pending(session)
