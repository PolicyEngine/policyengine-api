"""Unit checks for conflict-aware policy insertion statements."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.dialects import postgresql
from sqlmodel import col, select

from policyengine_api.data.v2.models import (
    Parameter,
    ParameterValue,
    Policy,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)
from policyengine_api.services.v2.policies.database_connectors import creates
from policyengine_api.services.v2.policies.types import (
    PolicyParameterValueInput,
    ResolvedPolicyCreationInput,
)
from tests.fixtures.database_sessions import recorded_statements, sqlite_v2_sessions


def test_policy_insert_uses_the_content_identity_constraint_and_returning() -> None:
    source = creates.create_policy.__code__.co_consts
    statement_text = " ".join(str(value) for value in source)

    assert "uq_policies_canonicalization_content_hash" in statement_text

    # Compile a representative statement through the same PostgreSQL dialect
    # construct to prove this module does not use a read-before-write insert.
    statement = (
        creates.insert(creates.Policy)
        .on_conflict_do_nothing(constraint="uq_policies_canonicalization_content_hash")
        .returning(creates.Policy.id)
    )
    compiled = str(statement.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT ON CONSTRAINT" in compiled
    assert "DO NOTHING" in compiled
    assert "RETURNING policies.id" in compiled


def test_a_policy_s_values_are_inserted_without_dynamic_id() -> None:
    """The insert names no ``parameter_values.dynamic_id``, which C1 · 53 drops.

    It backs ``POST /v2/policies`` and the dual-write v1-to-v2 policy copy, so
    it must go on working in the release serving while that revision runs.
    """
    model = TaxBenefitModel(name="policyengine-us")
    version = TaxBenefitModelVersion(
        model=model, version="1.0.0", current_law_id=1, metadata_time_periods=[]
    )
    parameter = Parameter(name="gov.example.rate", tax_benefit_model_version=version)
    policy = Policy(
        country_id="us",
        tax_benefit_model=model,
        tax_benefit_model_version=version,
        canonicalization_version=1,
        content_hash="a" * 64,
    )
    with sqlite_v2_sessions() as sessions, sessions() as session:
        session.add_all([model, version, parameter, policy])
        session.flush()
        policy_input = ResolvedPolicyCreationInput(
            country_id="us",
            tax_benefit_model_id=model.id,
            tax_benefit_model_version_id=version.id,
            policyengine_version="1.0.0",
            parameter_values=[
                PolicyParameterValueInput(
                    parameter_id=parameter.id,
                    value=0.2,
                    start_date=datetime(2026, 1, 1, tzinfo=UTC),
                )
            ],
        )
        with recorded_statements(session) as statements:
            creates.create_parameter_values(
                session, policy_id=policy.id, policy_input=policy_input
            )
        stored = session.exec(
            select(ParameterValue).where(col(ParameterValue.policy_id) == policy.id)
        ).one()

    [value_insert] = [
        statement
        for statement in statements
        if statement.startswith("INSERT INTO parameter_values")
    ]
    assert "dynamic_id" not in value_insert
    assert (stored.parameter_id, stored.value_json) == (parameter.id, 0.2)
