"""PostgreSQL tests for C1 · 48's split of stored policies holding model assumptions.

The command runs as the temporary role C1 · 49 creates, holding exactly
``POLICY_COPY_SPLIT_PRIVILEGES``, so a statement those grants don't allow
fails here. ``tests.integration.policy_copy_split_rows`` writes and removes
the rows as the disposable database's superuser, and assertions look only at
the rows a test wrote, since the command reads every stored policy.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlmodel import Session, col, select

from policyengine_api.data.v2.database import (
    unpooled_v2_read_only_sessions,
    unpooled_v2_sessions,
)
from policyengine_api.data.v2.models import (
    Dataset,
    Dynamic,
    Household,
    HouseholdJob,
    LegacyPolicyMapping,
    Policy,
    Report,
    Simulation,
    User,
    UserPolicy,
)
from policyengine_api.data.v2.privilege_reconciliation import (
    apply_declared_privileges,
    create_missing_roles,
)
from policyengine_api.data.v2.privileges import (
    POLICY_COPY_SPLIT_PRIVILEGES,
    POLICY_COPY_SPLIT_ROLE,
)
from policyengine_api.services.v2.policy_copy_split import services as split_services
from policyengine_api.services.v2.policy_copy_split.database_session import (
    PolicyCopySplitDatabaseSession,
)
from policyengine_api.services.v2.policy_copy_split.services import (
    V2PolicyCopySplitService,
    plan_policy_copy_split,
    read_policy_copy_ids,
    split_policy_copy_in_session,
)
from policyengine_api.services.v2.policy_copy_split.types import (
    PolicyCopyOutcome,
    PolicyCopyRefusalReason,
    PolicyCopySplit,
)
from scripts.split_v2_policy_copies import with_time_limits
from tests.fixtures.database_sessions import act_as
from tests.integration.policy_copy_split_rows import (
    CATALOG_VERSION,
    END_2026,
    Scenario,
    policy_exists,
    remove_scenario,
    saved_dynamics_of,
    saved_policy_target,
    split_for,
    store_catalog,
    store_dynamic,
    store_mapping,
    store_other_version,
    store_policy,
    store_saved_policy,
    store_user,
    stored_mapping,
    stored_values,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from sqlalchemy.orm import sessionmaker

US_TAX_RATE = "gov.irs.income.rate"
US_INCOME_ELASTICITY = "gov.simulation.labor_supply_responses.elasticities.income"
US_MTR_DELTA = "simulation.marginal_tax_rate_delta"
UK_TAX_RATE = "gov.hmrc.income_tax.rates.uk[0].rate"
UK_INCOME_ELASTICITY = "gov.simulation.labour_supply_responses.income_elasticity"
UK_OBR_SWITCH = "gov.dynamic.obr_labour_supply_assumptions"


@pytest.fixture(scope="module")
def owner_sessions(
    v2_owner_sessions: sessionmaker[Session],
) -> sessionmaker[Session]:
    """Session factories of the disposable database's owner, its superuser."""
    return v2_owner_sessions


@pytest.fixture(scope="module")
def split_role_sessions(
    v2_owner_sessions: sessionmaker[Session],
    v2_sessions_as_role: Callable[[str], sessionmaker[Session]],
) -> sessionmaker[Session]:
    """Session factories acting as the temporary role, with only its declared grants."""
    with v2_owner_sessions.begin() as session:
        create_missing_roles(session, [POLICY_COPY_SPLIT_ROLE])
        plan, _default_privileges = apply_declared_privileges(
            session, {POLICY_COPY_SPLIT_ROLE: POLICY_COPY_SPLIT_PRIVILEGES}
        )
    assert plan.can_apply
    return v2_sessions_as_role(POLICY_COPY_SPLIT_ROLE)


@pytest.fixture(scope="module")
def listing_sessions(
    disposable_v2_database_url: str, split_role_sessions: sessionmaker[Session]
) -> Iterator[sessionmaker[Session]]:
    """Yield the owner's READ ONLY Session factories, as the command's listing has.

    ``split_role_sessions`` creates the temporary role, which the listing's
    service acts as in each session.
    """
    with unpooled_v2_read_only_sessions(disposable_v2_database_url) as sessions:
        yield sessions


@pytest.fixture(scope="module")
def time_limited_sessions(
    disposable_v2_database_url: str, split_role_sessions: sessionmaker[Session]
) -> Iterator[sessionmaker[Session]]:
    """Yield the owner's Session factories with the command's time limits.

    Their URL is the command's (``with_time_limits``), so a lock wait ends as
    the command's does. ``split_role_sessions`` creates the temporary role.
    """
    url = with_time_limits(make_url(disposable_v2_database_url))
    with unpooled_v2_sessions(url) as sessions:
        yield sessions


class ActingAsTheSplitRole(PolicyCopySplitDatabaseSession):
    """Act as the temporary role in each of the owner's sessions (SET LOCAL ROLE)."""

    @contextmanager
    def read(self) -> Iterator[Session]:
        """Yield a session acting as the temporary role."""
        with super().read() as session:
            act_as(session, POLICY_COPY_SPLIT_ROLE)
            yield session

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        """Yield a transaction acting as the temporary role."""
        with super().transaction() as session:
            act_as(session, POLICY_COPY_SPLIT_ROLE)
            yield session


def _service(sessions: sessionmaker[Session]) -> V2PolicyCopySplitService:
    return V2PolicyCopySplitService(PolicyCopySplitDatabaseSession(sessions))


def _listing_service(sessions: sessionmaker[Session]) -> V2PolicyCopySplitService:
    return V2PolicyCopySplitService(ActingAsTheSplitRole(sessions))


@pytest.fixture
def us_scenario(owner_sessions: sessionmaker[Session]) -> Iterator[Scenario]:
    scenario = store_catalog(
        owner_sessions, "us", [US_TAX_RATE, US_INCOME_ELASTICITY, US_MTR_DELTA]
    )
    try:
        yield scenario
    finally:
        remove_scenario(owner_sessions, scenario)


@pytest.fixture
def uk_scenario(owner_sessions: sessionmaker[Session]) -> Iterator[Scenario]:
    scenario = store_catalog(
        owner_sessions, "uk", [UK_TAX_RATE, UK_INCOME_ELASTICITY, UK_OBR_SWITCH]
    )
    try:
        yield scenario
    finally:
        remove_scenario(owner_sessions, scenario)


def test_a_us_copy_is_split_re_pointed_given_a_saved_dynamic_and_deleted(
    owner_sessions: sessionmaker[Session],
    split_role_sessions: sessionmaker[Session],
    us_scenario: Scenario,
) -> None:
    scenario = us_scenario
    old_copy_id = store_policy(
        owner_sessions,
        scenario,
        scenario.parameter_value(US_TAX_RATE, value=0.3),
        scenario.parameter_value(US_INCOME_ELASTICITY, value=0.25),
        scenario.parameter_value(US_MTR_DELTA, value=0.01, end_date=None),
    )
    legacy_policy_id = store_mapping(owner_sessions, scenario, policy_id=old_copy_id)
    user_id = store_user(owner_sessions, scenario)
    saved_policy_id = store_saved_policy(
        owner_sessions,
        scenario,
        user_id=user_id,
        policy_id=old_copy_id,
        name="My reform",
        legacy_policy_id=legacy_policy_id,
        description="Raises the rate, with labour supply responses",
    )

    split = split_for(
        list(_service(split_role_sessions).split_policy_copies()), old_copy_id
    )

    assert split.applied
    assert split.outcome is PolicyCopyOutcome.DELETED
    assert split.country_id == "us"
    assert split.policyengine_version == CATALOG_VERSION
    assert split.policy is not None
    assert split.policy.created
    assert split.dynamic is not None
    assert split.dynamic.created
    new_policy_id, new_dynamic_id = split.policy.id, split.dynamic.id
    assert not policy_exists(owner_sessions, old_copy_id)
    assert stored_values(owner_sessions, policy_id=old_copy_id) == set()
    assert stored_values(owner_sessions, policy_id=new_policy_id) == {
        (scenario.parameter_ids[US_TAX_RATE], 0.3, END_2026)
    }
    assert stored_values(owner_sessions, dynamic_id=new_dynamic_id) == {
        (scenario.parameter_ids[US_INCOME_ELASTICITY], 0.25, END_2026),
        (scenario.parameter_ids[US_MTR_DELTA], 0.01, None),
    }
    mapping = stored_mapping(owner_sessions, scenario, legacy_policy_id)
    assert (mapping.policy_id, mapping.dynamic_id) == (new_policy_id, new_dynamic_id)
    [repointed_mapping] = split.mappings
    assert repointed_mapping.legacy_policy_id == legacy_policy_id
    assert repointed_mapping.previous_dynamic_id is None
    assert repointed_mapping.dynamic.id == new_dynamic_id
    assert saved_policy_target(owner_sessions, saved_policy_id) == new_policy_id
    [saved_dynamic] = saved_dynamics_of(owner_sessions, user_id)
    assert (saved_dynamic.dynamic_id, saved_dynamic.country_id) == (
        new_dynamic_id,
        "us",
    )
    assert (saved_dynamic.name, saved_dynamic.description) == ("My reform", None)
    [repointed_saved_policy] = split.saved_policies
    assert repointed_saved_policy.user_policy_id == saved_policy_id
    assert repointed_saved_policy.saved_dynamic_id == saved_dynamic.id
    assert repointed_saved_policy.saved_dynamic_created
    with split_role_sessions() as session:
        assert old_copy_id not in read_policy_copy_ids(session)

    second_run = list(_service(split_role_sessions).split_policy_copies())

    assert old_copy_id not in {split.old_policy_id for split in second_run}
    mapping_after = stored_mapping(owner_sessions, scenario, legacy_policy_id)
    assert (mapping_after.policy_id, mapping_after.dynamic_id) == (
        new_policy_id,
        new_dynamic_id,
    )
    assert saved_policy_target(owner_sessions, saved_policy_id) == new_policy_id
    assert [row.id for row in saved_dynamics_of(owner_sessions, user_id)] == [
        saved_dynamic.id
    ]


def test_a_uk_copy_of_only_model_assumptions_points_at_an_empty_policy(
    owner_sessions: sessionmaker[Session],
    split_role_sessions: sessionmaker[Session],
    uk_scenario: Scenario,
) -> None:
    scenario = uk_scenario
    old_copy_id = store_policy(
        owner_sessions, scenario, scenario.parameter_value(UK_OBR_SWITCH, value=False)
    )
    legacy_policy_id = store_mapping(owner_sessions, scenario, policy_id=old_copy_id)

    split = split_for(
        list(_service(split_role_sessions).split_policy_copies()), old_copy_id
    )

    assert split.outcome is PolicyCopyOutcome.DELETED
    mapping = stored_mapping(owner_sessions, scenario, legacy_policy_id)
    assert mapping.policy_id == split.policy.id
    assert stored_values(owner_sessions, policy_id=mapping.policy_id) == set()
    with owner_sessions() as session:
        empty_policy = session.get(Policy, mapping.policy_id)
        assert empty_policy.tax_benefit_model_version_id == scenario.version_id
    assert stored_values(owner_sessions, dynamic_id=mapping.dynamic_id) == {
        (scenario.parameter_ids[UK_OBR_SWITCH], False, END_2026)
    }
    assert not policy_exists(owner_sessions, old_copy_id)


def test_a_mapping_that_already_names_a_dynamic_gets_one_merged_dynamic(
    owner_sessions: sessionmaker[Session],
    split_role_sessions: sessionmaker[Session],
    uk_scenario: Scenario,
) -> None:
    scenario = uk_scenario
    old_copy_id = store_policy(
        owner_sessions,
        scenario,
        scenario.parameter_value(UK_TAX_RATE, value=0.21),
        scenario.parameter_value(UK_OBR_SWITCH, value=False),
    )
    earlier_dynamic_id = store_dynamic(
        owner_sessions,
        scenario,
        scenario.parameter_value(UK_INCOME_ELASTICITY, value=0.1),
    )
    legacy_policy_id = store_mapping(
        owner_sessions, scenario, policy_id=old_copy_id, dynamic_id=earlier_dynamic_id
    )
    user_id = store_user(owner_sessions, scenario)
    mapped_saved_policy_id = store_saved_policy(
        owner_sessions,
        scenario,
        user_id=user_id,
        policy_id=old_copy_id,
        name="Copied from v1",
        legacy_policy_id=legacy_policy_id,
    )
    native_saved_policy_id = store_saved_policy(
        owner_sessions, scenario, user_id=user_id, policy_id=old_copy_id, name="Native"
    )

    split = split_for(
        list(_service(split_role_sessions).split_policy_copies()), old_copy_id
    )

    assert split.outcome is PolicyCopyOutcome.DELETED
    mapping = stored_mapping(owner_sessions, scenario, legacy_policy_id)
    assert mapping.policy_id == split.policy.id
    assert stored_values(owner_sessions, policy_id=mapping.policy_id) == {
        (scenario.parameter_ids[UK_TAX_RATE], 0.21, END_2026)
    }
    merged_dynamic_id = mapping.dynamic_id
    assert merged_dynamic_id not in {earlier_dynamic_id, split.dynamic.id}
    assert stored_values(owner_sessions, dynamic_id=merged_dynamic_id) == {
        (scenario.parameter_ids[UK_INCOME_ELASTICITY], 0.1, END_2026),
        (scenario.parameter_ids[UK_OBR_SWITCH], False, END_2026),
    }
    assert stored_values(owner_sessions, dynamic_id=split.dynamic.id) == {
        (scenario.parameter_ids[UK_OBR_SWITCH], False, END_2026)
    }
    [repointed_mapping] = split.mappings
    assert repointed_mapping.previous_dynamic_id == earlier_dynamic_id
    assert repointed_mapping.dynamic.id == merged_dynamic_id
    saved_dynamics = {
        row.name: row.dynamic_id for row in saved_dynamics_of(owner_sessions, user_id)
    }
    assert saved_dynamics == {
        "Copied from v1": merged_dynamic_id,
        "Native": split.dynamic.id,
    }
    for saved_policy_id in (mapped_saved_policy_id, native_saved_policy_id):
        assert saved_policy_target(owner_sessions, saved_policy_id) == mapping.policy_id
    with owner_sessions() as session:
        assert session.get(Dynamic, earlier_dynamic_id) is not None


def test_a_copy_a_report_names_is_split_and_re_pointed_but_kept(
    owner_sessions: sessionmaker[Session],
    split_role_sessions: sessionmaker[Session],
    us_scenario: Scenario,
) -> None:
    scenario = us_scenario
    old_copy_id = store_policy(
        owner_sessions,
        scenario,
        scenario.parameter_value(US_TAX_RATE, value=0.3),
        scenario.parameter_value(US_INCOME_ELASTICITY, value=0.25),
    )
    legacy_policy_id = store_mapping(owner_sessions, scenario, policy_id=old_copy_id)
    user_id = store_user(owner_sessions, scenario)
    saved_policy_id = store_saved_policy(
        owner_sessions, scenario, user_id=user_id, policy_id=old_copy_id, name="Kept"
    )
    with owner_sessions() as session:
        report = Report(
            country="us",
            tax_benefit_model_id=scenario.model_id,
            policy_id=old_copy_id,
        )
        session.add(report)
        session.commit()
        report_id = report.id

    split = split_for(
        list(_service(split_role_sessions).split_policy_copies()), old_copy_id
    )

    assert split.outcome is PolicyCopyOutcome.KEPT
    assert (
        split.references.simulations,
        split.references.reports,
        split.references.household_jobs,
    ) == (0, 1, 0)
    assert policy_exists(owner_sessions, old_copy_id)
    assert len(stored_values(owner_sessions, policy_id=old_copy_id)) == 2
    with owner_sessions() as session:
        assert session.get(Report, report_id).policy_id == old_copy_id
    mapping = stored_mapping(owner_sessions, scenario, legacy_policy_id)
    assert (mapping.policy_id, mapping.dynamic_id) == (
        split.policy.id,
        split.dynamic.id,
    )
    assert saved_policy_target(owner_sessions, saved_policy_id) == split.policy.id
    [saved_dynamic] = saved_dynamics_of(owner_sessions, user_id)
    with split_role_sessions() as session:
        assert old_copy_id in read_policy_copy_ids(session)

    second_split = split_for(
        list(_service(split_role_sessions).split_policy_copies()), old_copy_id
    )

    assert second_split.outcome is PolicyCopyOutcome.KEPT
    assert second_split.mappings == ()
    assert second_split.saved_policies == ()
    assert [row.id for row in saved_dynamics_of(owner_sessions, user_id)] == [
        saved_dynamic.id
    ]
    with owner_sessions() as session:
        session.execute(delete(Report).where(Report.id == report_id))
        session.commit()


def test_a_conflicting_merge_refuses_the_copy_and_changes_nothing(
    owner_sessions: sessionmaker[Session],
    split_role_sessions: sessionmaker[Session],
    uk_scenario: Scenario,
) -> None:
    scenario = uk_scenario
    old_copy_id = store_policy(
        owner_sessions,
        scenario,
        scenario.parameter_value(UK_TAX_RATE, value=0.21),
        scenario.parameter_value(UK_INCOME_ELASTICITY, value=0.2),
    )
    earlier_dynamic_id = store_dynamic(
        owner_sessions,
        scenario,
        scenario.parameter_value(UK_INCOME_ELASTICITY, value=0.1),
    )
    legacy_policy_id = store_mapping(
        owner_sessions, scenario, policy_id=old_copy_id, dynamic_id=earlier_dynamic_id
    )
    user_id = store_user(owner_sessions, scenario)
    saved_policy_id = store_saved_policy(
        owner_sessions,
        scenario,
        user_id=user_id,
        policy_id=old_copy_id,
        name="Conflicting",
        legacy_policy_id=legacy_policy_id,
    )

    split = split_for(
        list(_service(split_role_sessions).split_policy_copies()), old_copy_id
    )

    assert split.outcome is PolicyCopyOutcome.REFUSED
    assert split.refusal_reason is PolicyCopyRefusalReason.CONFLICTING_DYNAMIC_VALUES
    assert policy_exists(owner_sessions, old_copy_id)
    mapping = stored_mapping(owner_sessions, scenario, legacy_policy_id)
    assert (mapping.policy_id, mapping.dynamic_id) == (old_copy_id, earlier_dynamic_id)
    assert saved_policy_target(owner_sessions, saved_policy_id) == old_copy_id
    assert saved_dynamics_of(owner_sessions, user_id) == []
    with owner_sessions() as session:
        stored = session.exec(
            select(Policy.id).where(Policy.tax_benefit_model_id == scenario.model_id)
        ).all()
        assert list(stored) == [old_copy_id]
        dynamics = session.exec(
            select(Dynamic.id).where(Dynamic.tax_benefit_model_id == scenario.model_id)
        ).all()
        assert list(dynamics) == [earlier_dynamic_id]


def test_the_listing_reads_only_and_reports_what_would_change(
    owner_sessions: sessionmaker[Session],
    split_role_sessions: sessionmaker[Session],
    us_scenario: Scenario,
    listing_sessions: sessionmaker[Session],
) -> None:
    scenario = us_scenario
    stored_policy_part_id = store_policy(
        owner_sessions, scenario, scenario.parameter_value(US_TAX_RATE, value=0.3)
    )
    old_copy_id = store_policy(
        owner_sessions,
        scenario,
        scenario.parameter_value(US_TAX_RATE, value=0.3),
        scenario.parameter_value(US_INCOME_ELASTICITY, value=0.25),
    )
    legacy_policy_id = store_mapping(owner_sessions, scenario, policy_id=old_copy_id)
    user_id = store_user(owner_sessions, scenario)
    saved_policy_id = store_saved_policy(
        owner_sessions, scenario, user_id=user_id, policy_id=old_copy_id, name="Listed"
    )

    split = split_for(
        _listing_service(listing_sessions).list_policy_copy_splits(),
        old_copy_id,
    )

    assert not split.applied
    assert split.outcome is PolicyCopyOutcome.DELETED
    assert (split.policy.id, split.policy.created) == (stored_policy_part_id, False)
    assert (split.dynamic.id, split.dynamic.created) == (None, True)
    [listed_mapping] = split.mappings
    assert listed_mapping.legacy_policy_id == legacy_policy_id
    assert listed_mapping.dynamic.content_hash == split.dynamic.content_hash
    [listed_saved_policy] = split.saved_policies
    assert listed_saved_policy.user_policy_id == saved_policy_id
    assert listed_saved_policy.saved_dynamic_id is None
    assert listed_saved_policy.saved_dynamic_created
    assert policy_exists(owner_sessions, old_copy_id)
    mapping = stored_mapping(owner_sessions, scenario, legacy_policy_id)
    assert (mapping.policy_id, mapping.dynamic_id) == (old_copy_id, None)
    assert saved_policy_target(owner_sessions, saved_policy_id) == old_copy_id
    assert saved_dynamics_of(owner_sessions, user_id) == []
    with owner_sessions() as session:
        dynamics = session.exec(
            select(Dynamic.id).where(Dynamic.tax_benefit_model_id == scenario.model_id)
        ).all()
        assert dynamics == []


def test_an_identical_saved_dynamic_is_reused_and_another_name_gets_its_own(
    owner_sessions: sessionmaker[Session],
    split_role_sessions: sessionmaker[Session],
    us_scenario: Scenario,
) -> None:
    scenario = us_scenario
    old_copy_id = store_policy(
        owner_sessions,
        scenario,
        scenario.parameter_value(US_TAX_RATE, value=0.3),
        scenario.parameter_value(US_INCOME_ELASTICITY, value=0.25),
    )
    user_id = store_user(owner_sessions, scenario)
    first_id, second_id, other_id, unnamed_id, also_unnamed_id = (
        store_saved_policy(
            owner_sessions, scenario, user_id=user_id, policy_id=old_copy_id, name=name
        )
        for name in ("Reform A", "Reform A", "Reform B", None, None)
    )

    split = split_for(
        list(_service(split_role_sessions).split_policy_copies()), old_copy_id
    )

    by_saved_policy = {
        repointed.user_policy_id: repointed for repointed in split.saved_policies
    }
    assert by_saved_policy[first_id].saved_dynamic_created
    assert not by_saved_policy[second_id].saved_dynamic_created
    assert (
        by_saved_policy[second_id].saved_dynamic_id
        == by_saved_policy[first_id].saved_dynamic_id
    )
    assert by_saved_policy[other_id].saved_dynamic_created
    assert by_saved_policy[unnamed_id].saved_dynamic_created
    assert not by_saved_policy[also_unnamed_id].saved_dynamic_created
    assert sorted(
        (row.name or "") for row in saved_dynamics_of(owner_sessions, user_id)
    ) == ["", "Reform A", "Reform B"]


def test_policies_setting_no_model_assumption_are_left_alone(
    owner_sessions: sessionmaker[Session],
    split_role_sessions: sessionmaker[Session],
    us_scenario: Scenario,
) -> None:
    scenario = us_scenario
    policy_id = store_policy(
        owner_sessions, scenario, scenario.parameter_value(US_TAX_RATE, value=0.3)
    )
    legacy_policy_id = store_mapping(owner_sessions, scenario, policy_id=policy_id)

    splits = list(_service(split_role_sessions).split_policy_copies())

    assert policy_id not in {split.old_policy_id for split in splits}
    assert policy_exists(owner_sessions, policy_id)
    assert stored_mapping(owner_sessions, scenario, legacy_policy_id).dynamic_id is None


def test_one_copy_splits_in_a_caller_owned_transaction(
    owner_sessions: sessionmaker[Session],
    split_role_sessions: sessionmaker[Session],
    uk_scenario: Scenario,
) -> None:
    """D4 · 1's migration reuses the split in a transaction of its own."""
    scenario = uk_scenario
    old_copy_id = store_policy(
        owner_sessions,
        scenario,
        scenario.parameter_value(UK_TAX_RATE, value=0.21),
        scenario.parameter_value(UK_OBR_SWITCH, value=False),
    )
    legacy_policy_id = store_mapping(owner_sessions, scenario, policy_id=old_copy_id)

    with split_role_sessions() as session:
        split = split_policy_copy_in_session(session, old_copy_id)
        session.rollback()

    assert split is not None
    assert split.outcome is PolicyCopyOutcome.DELETED
    assert policy_exists(owner_sessions, old_copy_id)
    assert (
        stored_mapping(owner_sessions, scenario, legacy_policy_id).policy_id
        == old_copy_id
    )

    with split_role_sessions() as session:
        assert split_policy_copy_in_session(session, uuid4()) is None


def test_a_copy_a_simulation_names_is_kept(
    owner_sessions: sessionmaker[Session],
    split_role_sessions: sessionmaker[Session],
    us_scenario: Scenario,
) -> None:
    scenario = us_scenario
    old_copy_id = store_policy(
        owner_sessions,
        scenario,
        scenario.parameter_value(US_TAX_RATE, value=0.3),
        scenario.parameter_value(US_INCOME_ELASTICITY, value=0.25),
    )
    with owner_sessions() as session:
        dataset = Dataset(
            name="split-test-dataset",
            year=2026,
            is_output_dataset=False,
            tax_benefit_model_version_id=scenario.version_id,
        )
        session.add(dataset)
        session.flush()
        simulation = Simulation(
            dataset_id=dataset.id,
            tax_benefit_model_version_id=scenario.version_id,
            policy_id=old_copy_id,
        )
        session.add(simulation)
        session.commit()
        simulation_id = simulation.id

    split = split_for(
        list(_service(split_role_sessions).split_policy_copies()), old_copy_id
    )

    assert split.outcome is PolicyCopyOutcome.KEPT
    assert (
        split.references.simulations,
        split.references.reports,
        split.references.household_jobs,
    ) == (1, 0, 0)
    assert policy_exists(owner_sessions, old_copy_id)
    with owner_sessions() as session:
        assert session.get(Simulation, simulation_id).policy_id == old_copy_id


def test_the_split_waits_for_a_live_saved_policy_copy_instead_of_deadlocking(
    owner_sessions: sessionmaker[Session],
    split_role_sessions: sessionmaker[Session],
    us_scenario: Scenario,
) -> None:
    """API v1's copy of a v1 saved policy locks the mapping, then names the copy.

    It holds the mapping row FOR UPDATE, then inserts a saved policy naming
    the mapped copy, whose foreign-key check locks the copy's row. The split
    takes the same two locks in the same order, so it waits for the copy to
    commit, and then re-points the saved policy the copy added.
    """
    scenario = us_scenario
    old_copy_id = store_policy(
        owner_sessions,
        scenario,
        scenario.parameter_value(US_TAX_RATE, value=0.3),
        scenario.parameter_value(US_INCOME_ELASTICITY, value=0.25),
    )
    legacy_policy_id = store_mapping(owner_sessions, scenario, policy_id=old_copy_id)
    user_id = store_user(owner_sessions, scenario)
    split_results: list[PolicyCopySplit] = []
    split_errors: list[Exception] = []

    def run_split() -> None:
        try:
            split_results.extend(_service(split_role_sessions).split_policy_copies())
        except DBAPIError as error:
            split_errors.append(error)

    split_thread = threading.Thread(target=run_split)
    with owner_sessions() as live_copy_session:
        live_copy_session.exec(
            select(LegacyPolicyMapping)
            .where(
                LegacyPolicyMapping.country_id == scenario.country_id,
                LegacyPolicyMapping.legacy_policy_id == legacy_policy_id,
            )
            .with_for_update()
        ).one()
        split_thread.start()
        # Give the split time to reach its locks while the mapping is held.
        time.sleep(0.5)
        saved_policy = UserPolicy(
            user_id=user_id,
            country_id=scenario.country_id,
            policy_id=old_copy_id,
            legacy_policy_id=legacy_policy_id,
            name="Saved while splitting",
        )
        live_copy_session.add(saved_policy)
        live_copy_session.commit()
        saved_policy_id = saved_policy.id
    split_thread.join(timeout=60)

    assert not split_thread.is_alive()
    assert split_errors == []
    split = split_for(split_results, old_copy_id)
    assert split.outcome is PolicyCopyOutcome.DELETED
    assert [repointed.user_policy_id for repointed in split.saved_policies] == [
        saved_policy_id
    ]
    assert saved_policy_target(owner_sessions, saved_policy_id) == split.policy.id
    assert not policy_exists(owner_sessions, old_copy_id)


def test_the_listing_reports_rows_an_earlier_copy_creates_as_reused(
    owner_sessions: sessionmaker[Session],
    split_role_sessions: sessionmaker[Session],
    uk_scenario: Scenario,
    listing_sessions: sessionmaker[Session],
) -> None:
    """Applying commits each copy before the next, so later copies reuse its rows.

    The listing reports what applying then does: the second copy's dynamic
    and saved dynamic are the first copy's.
    """
    scenario = uk_scenario
    copy_ids = [
        store_policy(
            owner_sessions,
            scenario,
            scenario.parameter_value(UK_TAX_RATE, value=tax_rate),
            scenario.parameter_value(UK_OBR_SWITCH, value=False),
        )
        for tax_rate in (0.21, 0.22)
    ]
    user_id = store_user(owner_sessions, scenario)
    for copy_id in copy_ids:
        store_saved_policy(
            owner_sessions, scenario, user_id=user_id, policy_id=copy_id, name=None
        )

    listed = _listing_service(listing_sessions).list_policy_copy_splits()
    applied = list(_service(split_role_sessions).split_policy_copies())

    def created_rows(split: PolicyCopySplit) -> tuple[bool, bool, list[bool]]:
        return (
            split.policy.created,
            split.dynamic.created,
            [saved.saved_dynamic_created for saved in split.saved_policies],
        )

    assert [created_rows(split_for(listed, copy_id)) for copy_id in copy_ids] == [
        (True, True, [True]),
        (True, False, [False]),
    ]
    assert [created_rows(split_for(applied, copy_id)) for copy_id in copy_ids] == [
        created_rows(split_for(listed, copy_id)) for copy_id in copy_ids
    ]
    assert len(saved_dynamics_of(owner_sessions, user_id)) == 1


def test_the_listing_s_sessions_refuse_writes(disposable_v2_database_url: str) -> None:
    with (
        unpooled_v2_read_only_sessions(disposable_v2_database_url) as sessions,
        sessions() as session,
    ):
        session.add(User(user_type="unauthenticated"))
        with pytest.raises(DBAPIError, match="read-only transaction"):
            session.flush()


def test_the_command_s_time_limits_reach_its_sessions(
    disposable_v2_database_url: str,
) -> None:
    url = with_time_limits(make_url(disposable_v2_database_url))

    with unpooled_v2_read_only_sessions(url) as sessions, sessions() as session:
        lock_timeout = session.exec(select(func.current_setting("lock_timeout")))
        assert lock_timeout.one() == "500ms"
        statement_timeout = session.exec(
            select(func.current_setting("statement_timeout"))
        )
        assert statement_timeout.one() == "1min"


def test_the_split_gives_way_to_a_live_sign_in_merge(
    owner_sessions: sessionmaker[Session],
    time_limited_sessions: sessionmaker[Session],
    us_scenario: Scenario,
) -> None:
    """API v1's sign-in merge locks the browser's user, then moves its saved policies.

    The split holds a saved policy's lock while saving its owner's dynamic,
    whose foreign-key check waits for the user's lock: a lock cycle. The
    split's wait ends first (its lock timeout is shorter than PostgreSQL's
    deadlock_timeout), so it rolls back, the merge commits, and the split
    tries the copy again, for the account the saved policy now belongs to.
    """
    scenario = us_scenario
    old_copy_id = store_policy(
        owner_sessions,
        scenario,
        scenario.parameter_value(US_TAX_RATE, value=0.3),
        scenario.parameter_value(US_INCOME_ELASTICITY, value=0.25),
    )
    browser_user_id = store_user(owner_sessions, scenario)
    account_user_id = store_user(owner_sessions, scenario)
    saved_policy_id = store_saved_policy(
        owner_sessions,
        scenario,
        user_id=browser_user_id,
        policy_id=old_copy_id,
        name="Saved before signing in",
    )
    service = V2PolicyCopySplitService(
        ActingAsTheSplitRole(time_limited_sessions),
        attempts=10,
        retry_delay_seconds=0.2,
    )
    split_results: list[PolicyCopySplit] = []
    split_errors: list[Exception] = []

    def run_split() -> None:
        try:
            split_results.extend(service.split_policy_copies())
        except DBAPIError as error:
            split_errors.append(error)

    split_thread = threading.Thread(target=run_split)
    with owner_sessions() as sign_in_session:
        sign_in_session.exec(
            select(User).where(User.id == browser_user_id).with_for_update()
        ).one()
        split_thread.start()
        # Give the split time to wait for the browser user's lock.
        time.sleep(0.3)
        sign_in_session.execute(
            update(UserPolicy)
            .where(col(UserPolicy.user_id) == browser_user_id)
            .values(user_id=account_user_id)
        )
        sign_in_session.commit()
    split_thread.join(timeout=60)

    assert not split_thread.is_alive()
    assert split_errors == []
    split = split_for(split_results, old_copy_id)
    assert split.outcome is PolicyCopyOutcome.DELETED
    with owner_sessions() as session:
        saved_policy = session.get(UserPolicy, saved_policy_id)
        assert (saved_policy.user_id, saved_policy.policy_id) == (
            account_user_id,
            split.policy.id,
        )
    [saved_dynamic] = saved_dynamics_of(owner_sessions, account_user_id)
    assert saved_dynamic.dynamic_id == split.dynamic.id
    assert saved_dynamics_of(owner_sessions, browser_user_id) == []


def test_the_split_gives_way_to_a_sign_in_merge_that_waits_first(
    owner_sessions: sessionmaker[Session],
    time_limited_sessions: sessionmaker[Session],
    us_scenario: Scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The merge waits for the saved policy first; the split joins the cycle later.

    Re-pointing the mapping is slowed by 0.7 seconds, as a remote database's
    round trips might slow the statements between locking the copy and
    saving the owner's dynamic. The merge, holding the browser user's lock,
    moves the saved policy meanwhile. It must commit, and the split must
    give the account the saved dynamic.
    """
    scenario = us_scenario
    old_copy_id = store_policy(
        owner_sessions,
        scenario,
        scenario.parameter_value(US_TAX_RATE, value=0.3),
        scenario.parameter_value(US_INCOME_ELASTICITY, value=0.25),
    )
    legacy_policy_id = store_mapping(owner_sessions, scenario, policy_id=old_copy_id)
    browser_user_id = store_user(owner_sessions, scenario)
    account_user_id = store_user(owner_sessions, scenario)
    saved_policy_id = store_saved_policy(
        owner_sessions,
        scenario,
        user_id=browser_user_id,
        policy_id=old_copy_id,
        legacy_policy_id=legacy_policy_id,
        name="Saved before signing in",
    )
    repoint_mapping = split_services.repoint_legacy_policy_mapping

    def slow_repoint_mapping(*arguments: object, **keywords: object) -> None:
        time.sleep(0.7)
        repoint_mapping(*arguments, **keywords)

    monkeypatch.setattr(
        split_services, "repoint_legacy_policy_mapping", slow_repoint_mapping
    )
    service = V2PolicyCopySplitService(
        ActingAsTheSplitRole(time_limited_sessions),
        attempts=10,
        retry_delay_seconds=0.2,
    )
    split_results: list[PolicyCopySplit] = []
    split_errors: list[Exception] = []

    def run_split() -> None:
        try:
            split_results.extend(service.split_policy_copies())
        except DBAPIError as error:
            split_errors.append(error)

    split_thread = threading.Thread(target=run_split)
    with owner_sessions() as sign_in_session:
        sign_in_session.exec(
            select(User).where(User.id == browser_user_id).with_for_update()
        ).one()
        split_thread.start()
        # The split is re-pointing the mapping, slowly, when the merge moves
        # the browser's saved policies.
        time.sleep(0.15)
        sign_in_session.execute(
            update(UserPolicy)
            .where(col(UserPolicy.user_id) == browser_user_id)
            .values(user_id=account_user_id)
        )
        sign_in_session.commit()
    split_thread.join(timeout=60)

    assert not split_thread.is_alive()
    assert split_errors == []
    split = split_for(split_results, old_copy_id)
    assert split.outcome is PolicyCopyOutcome.DELETED
    with owner_sessions() as session:
        saved_policy = session.get(UserPolicy, saved_policy_id)
        assert (saved_policy.user_id, saved_policy.policy_id) == (
            account_user_id,
            split.policy.id,
        )
    [saved_dynamic] = saved_dynamics_of(owner_sessions, account_user_id)
    assert saved_dynamic.dynamic_id == split.dynamic.id


def test_a_mapping_s_dynamic_on_another_catalog_version_refuses_the_copy(
    owner_sessions: sessionmaker[Session],
    split_role_sessions: sessionmaker[Session],
    uk_scenario: Scenario,
) -> None:
    scenario = uk_scenario
    old_copy_id = store_policy(
        owner_sessions,
        scenario,
        scenario.parameter_value(UK_TAX_RATE, value=0.21),
        scenario.parameter_value(UK_OBR_SWITCH, value=False),
    )
    other_version = store_other_version(
        owner_sessions, scenario, [UK_INCOME_ELASTICITY]
    )
    earlier_dynamic_id = store_dynamic(
        owner_sessions,
        other_version,
        other_version.parameter_value(UK_INCOME_ELASTICITY, value=0.1),
    )
    legacy_policy_id = store_mapping(
        owner_sessions, scenario, policy_id=old_copy_id, dynamic_id=earlier_dynamic_id
    )

    split = split_for(
        list(_service(split_role_sessions).split_policy_copies()), old_copy_id
    )

    assert split.outcome is PolicyCopyOutcome.REFUSED
    assert split.refusal_reason is PolicyCopyRefusalReason.DYNAMIC_ON_ANOTHER_CATALOG
    assert policy_exists(owner_sessions, old_copy_id)
    mapping = stored_mapping(owner_sessions, scenario, legacy_policy_id)
    assert (mapping.policy_id, mapping.dynamic_id) == (old_copy_id, earlier_dynamic_id)


def test_the_listing_reports_a_mapping_s_merged_dynamic_as_applying_does(
    owner_sessions: sessionmaker[Session],
    split_role_sessions: sessionmaker[Session],
    listing_sessions: sessionmaker[Session],
    uk_scenario: Scenario,
) -> None:
    scenario = uk_scenario
    old_copy_id = store_policy(
        owner_sessions,
        scenario,
        scenario.parameter_value(UK_TAX_RATE, value=0.21),
        scenario.parameter_value(UK_OBR_SWITCH, value=False),
    )
    earlier_dynamic_id = store_dynamic(
        owner_sessions,
        scenario,
        scenario.parameter_value(UK_INCOME_ELASTICITY, value=0.1),
    )
    store_mapping(
        owner_sessions, scenario, policy_id=old_copy_id, dynamic_id=earlier_dynamic_id
    )

    listed = split_for(
        _listing_service(listing_sessions).list_policy_copy_splits(), old_copy_id
    )
    applied = split_for(
        list(_service(split_role_sessions).split_policy_copies()), old_copy_id
    )

    [listed_mapping] = listed.mappings
    [applied_mapping] = applied.mappings
    assert listed_mapping.previous_dynamic_id == earlier_dynamic_id
    assert (listed_mapping.dynamic.id, listed_mapping.dynamic.created) == (None, True)
    assert listed_mapping.dynamic.content_hash == applied_mapping.dynamic.content_hash
    assert listed_mapping.dynamic.content_hash != listed.dynamic.content_hash
    assert applied_mapping.dynamic.created


def test_a_copy_a_household_calculation_names_is_kept(
    owner_sessions: sessionmaker[Session],
    split_role_sessions: sessionmaker[Session],
    us_scenario: Scenario,
) -> None:
    scenario = us_scenario
    old_copy_id = store_policy(
        owner_sessions,
        scenario,
        scenario.parameter_value(US_TAX_RATE, value=0.3),
        scenario.parameter_value(US_INCOME_ELASTICITY, value=0.25),
    )
    with owner_sessions() as session:
        household = Household(
            household_data={"people": {"you": {}}},
            country_id="us",
            canonicalization_version=1,
            content_hash=uuid4().hex * 2,
        )
        session.add(household)
        session.flush()
        household_job = HouseholdJob(
            country="us",
            household_id=household.id,
            year=2026,
            request_data={},
            policy_id=old_copy_id,
            tax_benefit_model_version_id=scenario.version_id,
            country_package_version="1.0.0",
            policyengine_version=CATALOG_VERSION,
        )
        session.add(household_job)
        session.commit()
        scenario.household_ids.append(household.id)

    split = split_for(
        list(_service(split_role_sessions).split_policy_copies()), old_copy_id
    )

    assert split.outcome is PolicyCopyOutcome.KEPT
    assert (
        split.references.simulations,
        split.references.reports,
        split.references.household_jobs,
    ) == (0, 0, 1)
    assert policy_exists(owner_sessions, old_copy_id)


def test_a_saved_policy_deleted_or_pointed_elsewhere_meanwhile_is_skipped(
    owner_sessions: sessionmaker[Session],
    split_role_sessions: sessionmaker[Session],
    us_scenario: Scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A saved policy the split read can change before the split locks it.

    It's skipped then: one deleted meanwhile, and one pointed at another
    policy, which keeps naming that policy and gets no saved dynamic.
    """
    scenario = us_scenario
    old_copy_id = store_policy(
        owner_sessions,
        scenario,
        scenario.parameter_value(US_TAX_RATE, value=0.3),
        scenario.parameter_value(US_INCOME_ELASTICITY, value=0.25),
    )
    other_policy_id = store_policy(
        owner_sessions, scenario, scenario.parameter_value(US_TAX_RATE, value=0.4)
    )
    user_id = store_user(owner_sessions, scenario)
    deleted_id, repointed_id = (
        store_saved_policy(
            owner_sessions, scenario, user_id=user_id, policy_id=old_copy_id, name=name
        )
        for name in ("Deleted meanwhile", "Pointed elsewhere meanwhile")
    )
    read_for_update = split_services.read_saved_policy_for_update
    changed: list[bool] = []

    def change_then_read(session: Session, saved_policy_id: UUID) -> UserPolicy | None:
        if not changed:
            with owner_sessions.begin() as other_session:
                other_session.execute(
                    delete(UserPolicy).where(col(UserPolicy.id) == deleted_id)
                )
                other_session.execute(
                    update(UserPolicy)
                    .where(col(UserPolicy.id) == repointed_id)
                    .values(policy_id=other_policy_id)
                )
            changed.append(True)
        return read_for_update(session, saved_policy_id)

    monkeypatch.setattr(
        split_services, "read_saved_policy_for_update", change_then_read
    )

    split = split_for(
        list(_service(split_role_sessions).split_policy_copies()), old_copy_id
    )

    assert split.outcome is PolicyCopyOutcome.DELETED
    assert split.saved_policies == ()
    assert not policy_exists(owner_sessions, old_copy_id)
    assert saved_policy_target(owner_sessions, repointed_id) == other_policy_id
    assert saved_dynamics_of(owner_sessions, user_id) == []


def test_the_listing_reports_a_refused_copy_and_skips_rows_with_nothing_to_split(
    owner_sessions: sessionmaker[Session],
    split_role_sessions: sessionmaker[Session],
    listing_sessions: sessionmaker[Session],
    uk_scenario: Scenario,
) -> None:
    scenario = uk_scenario
    refused_copy_id = store_policy(
        owner_sessions,
        scenario,
        scenario.parameter_value(UK_TAX_RATE, value=0.21),
        scenario.parameter_value(UK_INCOME_ELASTICITY, value=0.2),
    )
    earlier_dynamic_id = store_dynamic(
        owner_sessions,
        scenario,
        scenario.parameter_value(UK_INCOME_ELASTICITY, value=0.1),
    )
    store_mapping(
        owner_sessions,
        scenario,
        policy_id=refused_copy_id,
        dynamic_id=earlier_dynamic_id,
    )
    policy_without_assumptions_id = store_policy(
        owner_sessions, scenario, scenario.parameter_value(UK_TAX_RATE, value=0.22)
    )

    listed = split_for(
        _listing_service(listing_sessions).list_policy_copy_splits(),
        refused_copy_id,
    )

    assert not listed.applied
    assert listed.outcome is PolicyCopyOutcome.REFUSED
    assert listed.refusal_reason is PolicyCopyRefusalReason.CONFLICTING_DYNAMIC_VALUES
    with split_role_sessions() as session:
        for policy_id in (policy_without_assumptions_id, uuid4()):
            assert plan_policy_copy_split(session, policy_id) is None
            assert split_policy_copy_in_session(session, policy_id) is None
        session.rollback()


def test_the_count_of_copies_left_names_the_ones_kept(
    owner_sessions: sessionmaker[Session],
    split_role_sessions: sessionmaker[Session],
    us_scenario: Scenario,
) -> None:
    scenario = us_scenario
    deleted_copy_id, kept_copy_id = (
        store_policy(
            owner_sessions,
            scenario,
            scenario.parameter_value(US_TAX_RATE, value=tax_rate),
            scenario.parameter_value(US_INCOME_ELASTICITY, value=0.25),
        )
        for tax_rate in (0.3, 0.4)
    )
    with owner_sessions.begin() as session:
        session.add(
            Report(
                country="us",
                tax_benefit_model_id=scenario.model_id,
                policy_id=kept_copy_id,
            )
        )
    service = _service(split_role_sessions)

    list(service.split_policy_copies())

    with split_role_sessions() as session:
        remaining_copy_ids = read_policy_copy_ids(session)
    assert kept_copy_id in remaining_copy_ids
    assert deleted_copy_id not in remaining_copy_ids
    assert service.count_policy_copies() == len(remaining_copy_ids)
