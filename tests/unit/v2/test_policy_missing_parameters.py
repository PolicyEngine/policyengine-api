"""Report the parameters a stored v2 policy sets that the running catalog lacks."""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session, create_engine

from policyengine_api.data.v2.models import (
    V2_METADATA,
    Parameter,
    ParameterValue,
    Policy,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)
from policyengine_api.services.v2.policies.database_connectors.reads import (
    PARAMETER_NAME_BATCH_SIZE,
    read_parameters_by_name,
)
from policyengine_api.services.v2.policies.database_session import (
    PolicyDatabaseSession,
)
from policyengine_api.services.v2.policies.services import V2PolicyService
from tests.fixtures.recording_session import RecordingSession

RUNNING_VERSION = "5.2.0"
EARLIER_VERSION = "5.1.0"
KEPT_PARAMETER = "gov.example.rate"
REMOVED_PARAMETER = "gov.example.removed_rate"


@pytest.fixture
def engine():
    database_engine = create_engine("sqlite://")
    V2_METADATA.create_all(database_engine)
    yield database_engine
    database_engine.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as database_session:
        yield database_session


def _service(engine, running_policyengine_version: str = RUNNING_VERSION):
    sessions = sessionmaker(engine, class_=Session, expire_on_commit=False)
    return V2PolicyService(
        PolicyDatabaseSession(sessions),
        running_policyengine_version=running_policyengine_version,
    )


def _version(
    session: Session, model: TaxBenefitModel, version: str, names: list[str]
) -> tuple[TaxBenefitModelVersion, dict[str, Parameter]]:
    model_version = TaxBenefitModelVersion(
        model=model,
        version=version,
        current_law_id=1,
        metadata_time_periods=[2026],
    )
    parameters = {
        name: Parameter(name=name, tax_benefit_model_version=model_version)
        for name in names
    }
    session.add(model_version)
    session.add_all(parameters.values())
    session.commit()
    return model_version, parameters


def _policy(
    session: Session,
    model_version: TaxBenefitModelVersion,
    parameters: dict[str, Parameter],
    *,
    content_hash: str,
) -> Policy:
    policy = Policy(
        country_id="us",
        tax_benefit_model_id=model_version.model_id,
        tax_benefit_model_version_id=model_version.id,
        canonicalization_version=1,
        content_hash=content_hash * 64,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    session.add(policy)
    session.flush()
    session.add_all(
        ParameterValue(
            parameter_id=parameter.id,
            value_json=0.2,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
            policy_id=policy.id,
        )
        for parameter in parameters.values()
    )
    session.commit()
    return policy


@pytest.fixture
def stored_policies(session: Session) -> dict[str, Policy]:
    """Store a policy on an earlier catalog version and one on the running one."""
    model = TaxBenefitModel(name="policyengine-us")
    earlier, earlier_parameters = _version(
        session, model, EARLIER_VERSION, [KEPT_PARAMETER, REMOVED_PARAMETER]
    )
    running, running_parameters = _version(
        session, model, RUNNING_VERSION, [KEPT_PARAMETER]
    )
    return {
        "earlier": _policy(session, earlier, earlier_parameters, content_hash="a"),
        "running": _policy(session, running, running_parameters, content_hash="b"),
    }


def test_policy_on_an_earlier_catalog_names_the_parameters_the_running_one_lacks(
    engine, stored_policies: dict[str, Policy]
) -> None:
    policy = _service(engine).get_policy(
        country_id="us", policy_id=stored_policies["earlier"].id
    )

    assert policy.missing_parameters == (REMOVED_PARAMETER,)


def test_policy_on_the_running_catalog_lacks_nothing(
    engine, stored_policies: dict[str, Policy]
) -> None:
    policy = _service(engine).get_policy(
        country_id="us", policy_id=stored_policies["running"].id
    )

    assert policy.missing_parameters == ()


def test_page_reports_each_policy_against_the_running_catalog(
    engine, stored_policies: dict[str, Policy]
) -> None:
    page = _service(engine).list_policies(country_id="us", offset=0, limit=10)

    assert {item.id: item.missing_parameters for item in page.items} == {
        stored_policies["earlier"].id: (REMOVED_PARAMETER,),
        stored_policies["running"].id: (),
    }


def test_without_a_running_catalog_nothing_is_reported(
    engine, stored_policies: dict[str, Policy]
) -> None:
    # The running PolicyEngine.py release has no published catalog yet.
    policy = _service(engine, running_policyengine_version="9.9.9").get_policy(
        country_id="us", policy_id=stored_policies["earlier"].id
    )

    assert policy.missing_parameters is None


def test_parameter_names_are_read_in_batches_of_bounded_size() -> None:
    # A page of policies on an earlier catalog can name tens of thousands of
    # parameters; PostgreSQL drivers refuse more than 65,535 bound values.
    names = {f"gov.example.parameter_{index}" for index in range(2_500)}
    session = RecordingSession(results=deque([[], [], []]))

    found = read_parameters_by_name(session, model_version_id=uuid4(), names=names)

    statements = [
        operation for operation in session.operations if operation[0] == "exec"
    ]
    name_batches = [
        value
        for _method, _sql, parameters in statements
        for value in parameters.values()
        if isinstance(value, list)
    ]
    assert found == {}
    assert len(statements) == 3
    assert all(len(batch) <= PARAMETER_NAME_BATCH_SIZE for batch in name_batches)
    assert sorted(name for batch in name_batches for name in batch) == sorted(names)
