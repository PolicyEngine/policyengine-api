"""Check the revision that drops ``parameter_values.dynamic_id`` against Postgres.

Revision 1c651058fac5, on the dynamic parameter tables revision 7f7335f0eb31,
drops ``parameter_values.dynamic_id`` with its key to ``dynamics``, the
single-owner check and the per-dynamic partial unique index: revision
7f7335f0eb31 moved every dynamic's values to ``dynamic_parameter_values``.
PostgreSQL also drops the current-law index, whose condition named the column,
so the revision creates it again under a new name with ``policy_id IS NULL``.
The downgrade restores the column, key, check and both indexes, so that the
downgrade through 7f7335f0eb31 can copy dynamics' values back.

The rows are written as the disposable database's owner.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from sqlalchemy import delete, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlmodel import col

from policyengine_api.data.v2.migration_target import V2_ALEMBIC_DISPOSABLE_TEST
from policyengine_api.data.v2.models import (
    Dynamic,
    DynamicParameter,
    DynamicParameterValue,
    Parameter,
    ParameterValue,
    Policy,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)
from policyengine_api.data.v2.privilege_reconciliation import (
    DEPLOYMENT_ENVIRONMENT,
    run,
)
from policyengine_api.data.v2.settings import V2_MIGRATION_DATABASE_URL
from tests.fixtures.database_sessions import schema_inspector
from tests.fixtures.integration.alembic_v2 import alembic_v2_config, table_columns
from tests.integration.alembic_version_rows import current_revision
from tests.integration.parameter_values_with_dynamics import (
    ParameterValueWithDynamic,
)
from tests.integration.simulation_rows import (
    PublicApiRows,
    add_row,
    delete_public_api_rows,
    insert_public_api_rows,
    refused,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

    from tests.integration.conftest import ManagedV2Roles

USER_DYNAMICS_REVISION = "d417fe8b1b17"
DYNAMIC_PARAMETER_TABLES_REVISION = "7f7335f0eb31"
DYNAMIC_ID_DROP_REVISION = "1c651058fac5"
CURRENT_LAW_INDEX = "uq_parameter_values_current_law_parameter_start_date"
START_2026 = datetime(2026, 1, 1, tzinfo=UTC)
START_2027 = datetime(2027, 1, 1, tzinfo=UTC)
US_ELASTICITY = "gov.simulation.labor_supply_responses.elasticity"


def _schema_shape(sessions: sessionmaker[Session]) -> dict[str, dict[str, Any]]:
    """Reflect every table's columns, keys, indexes and checks, by name."""
    inspector = schema_inspector(sessions)
    return {
        table_name: {
            "columns": {
                column["name"]: (
                    column["type"].compile(dialect=postgresql.dialect()),
                    column["nullable"],
                    column.get("default"),
                )
                for column in inspector.get_columns(table_name)
            },
            "primary_key": inspector.get_pk_constraint(table_name),
            "foreign_keys": {
                key["name"]: (
                    tuple(key["constrained_columns"]),
                    key["referred_table"],
                    key["options"].get("ondelete"),
                )
                for key in inspector.get_foreign_keys(table_name)
            },
            "unique_constraints": {
                unique["name"]: tuple(unique["column_names"])
                for unique in inspector.get_unique_constraints(table_name)
            },
            "indexes": {
                index["name"]: (
                    tuple(index["column_names"]),
                    index["unique"],
                    index.get("dialect_options", {}).get("postgresql_where"),
                )
                for index in inspector.get_indexes(table_name)
            },
            "checks": {
                check["name"]: check["sqltext"]
                for check in inspector.get_check_constraints(table_name)
            },
        }
        for table_name in inspector.get_table_names(schema="public")
        if table_name != "alembic_version"
    }


def _expected_after_the_drop(
    parent_shape: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Return the parent's schema less the dynamic's columns, with the new index."""
    expected = deepcopy(parent_shape)
    values = expected["parameter_values"]
    del values["columns"]["dynamic_id"]
    del values["foreign_keys"]["fk_parameter_values_dynamic_id_dynamics"]
    del values["checks"]["ck_parameter_values_single_owner"]
    del values["indexes"]["uq_parameter_values_dynamic_parameter_start_date"]
    del values["indexes"]["uq_parameter_values_canonical_parameter_start_date"]
    values["indexes"][CURRENT_LAW_INDEX] = (
        ("parameter_id", "start_date"),
        True,
        "(policy_id IS NULL)",
    )
    return expected


def _privilege_environment(
    database_url: str, managed_v2_roles: ManagedV2Roles
) -> dict[str, str]:
    """Return what the deploy's privilege steps read."""
    return {
        V2_MIGRATION_DATABASE_URL: database_url,
        V2_ALEMBIC_DISPOSABLE_TEST: "1",
        DEPLOYMENT_ENVIRONMENT: managed_v2_roles.deployment_environment,
    }


@pytest.fixture
def sessions(
    v2_owner_sessions: sessionmaker[Session],
    disposable_v2_database_url: str,
    managed_v2_roles: ManagedV2Roles,
) -> Iterator[sessionmaker[Session]]:
    """Yield the owner's Session factories; leave the database at the v2 head.

    Downgrading to the base removes every table and its grants, so the roles
    get theirs back for the tests that run after this one.
    """
    command.upgrade(alembic_v2_config(), "head")
    try:
        yield v2_owner_sessions
    finally:
        command.upgrade(alembic_v2_config(), "head")
        apply_status = run(
            "apply",
            environ=_privilege_environment(
                disposable_v2_database_url, managed_v2_roles
            ),
        )
    assert apply_status == 0


def _build_parent_schema(sessions: sessionmaker[Session]) -> dict[str, dict[str, Any]]:
    """Build the parent revision from the base, without this revision's downgrade."""
    config = alembic_v2_config()
    command.downgrade(config, "base")
    command.upgrade(config, DYNAMIC_PARAMETER_TABLES_REVISION)
    return _schema_shape(sessions)


def test_the_revision_drops_only_what_a_dynamic_s_values_needed(
    sessions: sessionmaker[Session],
) -> None:
    """The drop, and a current-law index with no ``dynamic_id`` in its condition.

    The downgrade gives back exactly the parent's schema.
    """
    config = alembic_v2_config()
    parent_shape = _build_parent_schema(sessions)

    command.upgrade(config, DYNAMIC_ID_DROP_REVISION)

    assert _schema_shape(sessions) == _expected_after_the_drop(parent_shape)

    command.downgrade(config, DYNAMIC_PARAMETER_TABLES_REVISION)

    assert _schema_shape(sessions) == parent_shape


def _add_parameter(session: Session, rows: PublicApiRows, name: str) -> UUID:
    parameter_id = uuid4()
    add_row(
        session,
        Parameter,
        id=parameter_id,
        name=name,
        tax_benefit_model_version_id=rows.version_id,
    )
    return parameter_id


def _add_policy(session: Session, rows: PublicApiRows) -> UUID:
    policy_id = uuid4()
    add_row(
        session,
        Policy,
        id=policy_id,
        country_id="us",
        tax_benefit_model_id=rows.model_id,
        tax_benefit_model_version_id=rows.version_id,
        canonicalization_version=1,
        content_hash=uuid4().hex * 2,
    )
    return policy_id


def _add_dynamic(session: Session, model_id: UUID, version_id: UUID) -> UUID:
    dynamic_id = uuid4()
    add_row(
        session,
        Dynamic,
        id=dynamic_id,
        country_id="us",
        tax_benefit_model_id=model_id,
        tax_benefit_model_version_id=version_id,
        canonicalization_version=1,
        content_hash=uuid4().hex * 2,
    )
    return dynamic_id


def _delete_catalog_rows(
    session: Session, rows: PublicApiRows, *, policy_ids: list[UUID]
) -> None:
    """Delete the policies and dynamics, then the version with its parameters."""
    session.execute(delete(Policy).where(col(Policy.id).in_(policy_ids)))
    session.execute(
        delete(Dynamic).where(
            col(Dynamic.tax_benefit_model_version_id) == rows.version_id
        )
    )
    session.execute(
        delete(Parameter).where(
            col(Parameter.tax_benefit_model_version_id) == rows.version_id
        )
    )
    delete_public_api_rows(session, rows)


def test_rows_survive_and_a_parameter_keeps_one_current_law_value_per_date(
    sessions: sessionmaker[Session],
) -> None:
    """A current-law value and a policy's value stay, and the new index refuses.

    The index covers every value with no policy, and no policy's value.
    """
    config = alembic_v2_config()
    command.downgrade(config, DYNAMIC_PARAMETER_TABLES_REVISION)
    with sessions.begin() as session:
        rows = insert_public_api_rows(session)
        parameter_id = _add_parameter(session, rows, "gov.irs.rate")
        policy_id = _add_policy(session, rows)
        current_law_value_id = uuid4()
        policy_value_id = uuid4()
        current_law = {
            "parameter_id": parameter_id,
            "value_json": 0.5,
            "start_date": START_2026,
        }
        add_row(session, ParameterValue, id=current_law_value_id, **current_law)
        add_row(
            session,
            ParameterValue,
            id=policy_value_id,
            **{**current_law, "value_json": 0.4},
            policy_id=policy_id,
        )
    try:
        command.upgrade(config, DYNAMIC_ID_DROP_REVISION)

        with sessions() as session:
            stored = set(
                session.execute(
                    select(
                        col(ParameterValue.id),
                        col(ParameterValue.policy_id),
                        col(ParameterValue.value_json),
                    ).where(col(ParameterValue.parameter_id) == parameter_id)
                )
            )
            assert stored == {
                (current_law_value_id, None, 0.5),
                (policy_value_id, policy_id, 0.4),
            }
            with refused(session, match=CURRENT_LAW_INDEX):
                add_row(session, ParameterValue, id=uuid4(), **current_law)
            # Another policy may set the same parameter from the same date.
            other_policy_id = _add_policy(session, rows)
            add_row(
                session,
                ParameterValue,
                id=uuid4(),
                **current_law,
                policy_id=other_policy_id,
            )
            session.rollback()
    finally:
        with sessions.begin() as session:
            _delete_catalog_rows(session, rows, policy_ids=[policy_id])


def _us_model_id(session: Session) -> tuple[UUID, bool]:
    """Return ``policyengine-us``'s model, storing it first if it isn't stored.

    The dynamic parameter tables revision classifies a version's parameters
    by its model's name, so a round trip through it needs this model.
    """
    stored = session.scalars(
        select(col(TaxBenefitModel.id)).where(
            col(TaxBenefitModel.name) == "policyengine-us"
        )
    ).one_or_none()
    if stored is not None:
        return stored, False
    model_id = uuid4()
    add_row(session, TaxBenefitModel, id=model_id, name="policyengine-us")
    return model_id, True


def test_a_downgrade_through_the_move_puts_a_dynamic_s_values_back(
    sessions: sessionmaker[Session],
) -> None:
    """The restored column takes a dynamic's values back, and the upgrades move them.

    The downgrade through 7f7335f0eb31 copies dynamics' values into
    ``parameter_values`` with their ``dynamic_id``, where the restored check
    and per-dynamic index apply again. Upgrading to the head moves them back
    to ``dynamic_parameter_values`` and drops the column again.
    """
    config = alembic_v2_config()
    with sessions.begin() as session:
        model_id, model_created = _us_model_id(session)
        version_id = uuid4()
        add_row(
            session,
            TaxBenefitModelVersion,
            id=version_id,
            model_id=model_id,
            version=f"c1-53-{version_id.hex[:12]}",
            current_law_id=1,
            metadata_time_periods=[2026],
        )
        parameter_id = uuid4()
        add_row(
            session,
            DynamicParameter,
            id=parameter_id,
            name=US_ELASTICITY,
            tax_benefit_model_version_id=version_id,
        )
        dynamic_id = _add_dynamic(session, model_id, version_id)
        current_law_value_id = uuid4()
        dynamic_value_id = uuid4()
        add_row(
            session,
            DynamicParameterValue,
            id=current_law_value_id,
            dynamic_parameter_id=parameter_id,
            value_json=0.0,
            start_date=START_2026,
        )
        add_row(
            session,
            DynamicParameterValue,
            id=dynamic_value_id,
            dynamic_parameter_id=parameter_id,
            dynamic_id=dynamic_id,
            value_json=0.3,
            start_date=START_2027,
        )
    try:
        command.downgrade(config, USER_DYNAMICS_REVISION)

        with sessions() as session:
            restored = set(
                session.execute(
                    select(
                        ParameterValueWithDynamic.id,
                        ParameterValueWithDynamic.dynamic_id,
                        ParameterValueWithDynamic.policy_id,
                    ).where(ParameterValueWithDynamic.parameter_id == parameter_id)
                )
            )
            assert restored == {
                (current_law_value_id, None, None),
                (dynamic_value_id, dynamic_id, None),
            }
            dynamic_value = {
                "parameter_id": parameter_id,
                "dynamic_id": dynamic_id,
                "value_json": 0.4,
                "start_date": START_2027,
            }
            with refused(
                session, match="uq_parameter_values_dynamic_parameter_start_date"
            ):
                add_row(session, ParameterValueWithDynamic, id=uuid4(), **dynamic_value)
            policy_id = uuid4()
            add_row(
                session,
                Policy,
                id=policy_id,
                country_id="us",
                tax_benefit_model_id=model_id,
                tax_benefit_model_version_id=version_id,
                canonicalization_version=1,
                content_hash=uuid4().hex * 2,
            )
            with refused(session, match="ck_parameter_values_single_owner"):
                add_row(
                    session,
                    ParameterValueWithDynamic,
                    id=uuid4(),
                    **{**dynamic_value, "start_date": START_2026},
                    policy_id=policy_id,
                )
            session.rollback()

        command.upgrade(config, "head")

        assert "dynamic_id" not in table_columns(sessions, "parameter_values")
        with sessions() as session:
            moved = set(
                session.execute(
                    select(
                        col(DynamicParameterValue.id),
                        col(DynamicParameterValue.dynamic_id),
                    ).where(
                        col(DynamicParameterValue.dynamic_parameter_id) == parameter_id
                    )
                )
            )
        assert moved == {(current_law_value_id, None), (dynamic_value_id, dynamic_id)}
    finally:
        command.upgrade(config, "head")
        with sessions.begin() as session:
            session.execute(delete(Dynamic).where(col(Dynamic.id) == dynamic_id))
            session.execute(
                delete(TaxBenefitModelVersion).where(
                    col(TaxBenefitModelVersion.id) == version_id
                )
            )
            if model_created:
                session.execute(
                    delete(TaxBenefitModel).where(col(TaxBenefitModel.id) == model_id)
                )


def test_a_value_still_naming_a_dynamic_becomes_current_law_unless_it_clashes(
    sessions: sessionmaker[Session],
) -> None:
    """Why an operator counts such values before the merge (C1 · 53, decision 3).

    None should exist after 7f7335f0eb31. One that shares its parameter and
    start date with a current-law value fails the new index, and the upgrade
    changes nothing; any other silently becomes a current-law value.
    """
    config = alembic_v2_config()
    command.downgrade(config, DYNAMIC_PARAMETER_TABLES_REVISION)
    with sessions.begin() as session:
        rows = insert_public_api_rows(session)
        parameter_id = _add_parameter(session, rows, "gov.irs.rate")
        dynamic_id = _add_dynamic(session, rows.model_id, rows.version_id)
        add_row(
            session,
            ParameterValue,
            id=uuid4(),
            parameter_id=parameter_id,
            value_json=0.5,
            start_date=START_2026,
        )
        stray_value_id = uuid4()
        add_row(
            session,
            ParameterValueWithDynamic,
            id=stray_value_id,
            parameter_id=parameter_id,
            dynamic_id=dynamic_id,
            value_json=0.3,
            start_date=START_2026,
        )
    try:
        with pytest.raises(IntegrityError, match=CURRENT_LAW_INDEX):
            command.upgrade(config, DYNAMIC_ID_DROP_REVISION)

        assert current_revision(sessions) == DYNAMIC_PARAMETER_TABLES_REVISION
        with sessions.begin() as session:
            assert session.scalars(
                select(ParameterValueWithDynamic.dynamic_id).where(
                    ParameterValueWithDynamic.id == stray_value_id
                )
            ).all() == [dynamic_id]
            session.execute(
                update(ParameterValueWithDynamic)
                .where(ParameterValueWithDynamic.id == stray_value_id)
                .values(start_date=START_2027)
            )

        command.upgrade(config, DYNAMIC_ID_DROP_REVISION)

        with sessions() as session:
            assert session.scalars(
                select(col(ParameterValue.policy_id)).where(
                    col(ParameterValue.id) == stray_value_id
                )
            ).all() == [None]
    finally:
        with sessions.begin() as session:
            _delete_catalog_rows(session, rows, policy_ids=[])


def test_the_deploys_privilege_steps_pass_after_the_upgrade(
    sessions: sessionmaker[Session],
    disposable_v2_database_url: str,
    managed_v2_roles: ManagedV2Roles,
) -> None:
    """``apply`` and ``verify`` pass on the head after an upgrade from the parent."""
    config = alembic_v2_config()
    command.downgrade(config, DYNAMIC_PARAMETER_TABLES_REVISION)
    command.upgrade(config, "head")
    environ = _privilege_environment(disposable_v2_database_url, managed_v2_roles)

    assert run("apply", environ=environ) == 0
    assert run("verify", environ=environ) == 0
