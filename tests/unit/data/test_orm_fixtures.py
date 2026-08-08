from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from policyengine_api.data.v1_models import Household


def test_orm_session_factory_uses_mapped_models_and_python_json(
    orm_session_factory,
):
    assert isinstance(orm_session_factory, sessionmaker)

    with orm_session_factory.begin() as session:
        household = Household(
            country_id="uk",
            label="Fixture household",
            api_version="1.0.0",
            household_json={"people": {"you": {"age": {"2025": 40}}}},
            household_hash="fixture-hash",
        )
        session.add(household)

    with orm_session_factory() as session:
        stored = session.scalar(
            select(Household).where(Household.household_hash == "fixture-hash")
        )

    assert stored is not None
    assert stored.household_json == {"people": {"you": {"age": {"2025": 40}}}}


def test_orm_session_fixture_is_a_live_session(orm_session):
    assert isinstance(orm_session, Session)
    assert orm_session.is_active
