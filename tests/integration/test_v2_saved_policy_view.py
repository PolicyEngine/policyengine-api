"""The release before the saved-policy rename keeps working through the view.

Revision ``fa7fa1035444`` renames ``user_policies`` to
``user_policy_associations`` and keeps a temporary view under the old name. The
Public API release that still serves during the deploy, or after a rollback to
it, runs the same statements as today's services with the old table name.
These tests run today's services as the runtime role, rewrite each statement's
table name to ``user_policies`` before it is sent, as that release would
compile it, and check the result in the renamed table.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, delete, event, select, text
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS, POLICYENGINE_VERSION
from policyengine_api.data.v2.models import (
    LegacyPolicyMapping,
    LegacyUserMapping,
    Parameter,
    ParameterValue,
    Policy,
    TaxBenefitModel,
    TaxBenefitModelVersion,
    User,
    UserIdentity,
)
from policyengine_api.services.v2.identity.types import (
    UnauthenticatedPrincipal,
    UserPrincipal,
)
from policyengine_api.services.v2.policies.types import LegacyPolicySnapshot
from policyengine_api.services.v2.user_accounts.database_session import (
    AccountDatabaseSession,
)
from policyengine_api.services.v2.user_accounts.services import V2AccountService
from policyengine_api.services.v2.user_policies.database_session import (
    UserPolicyDatabaseSession,
)
from policyengine_api.services.v2.user_policies.services import (
    V2UserPolicyService,
    mirror_legacy_user_policy_in_session,
)
from policyengine_api.services.v2.user_policies.types import (
    LegacyUserPolicySnapshot,
    UserPolicyCreateFields,
    UserPolicyUpdateInput,
)
from policyengine_api.services.v2.user_reports.database_session import (
    UserReportDatabaseSession,
)
from policyengine_api.services.v2.user_reports.services import V2UserReportService
from policyengine_api.services.v2.user_reports.types import UserReportCreateFields
from tests.unit.v2.user_service_support import default_legacy_references

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Engine

TABLE_BEFORE_THE_RENAME = "user_policies"
TABLE_AFTER_THE_RENAME = "user_policy_associations"
# The renamed table where a statement names it as a table, not inside a label
# such as ``user_policy_associations_id``.
RENAMED_TABLE_REFERENCE = re.compile(rf"\b{TABLE_AFTER_THE_RENAME}\b")
MIRRORED_LEGACY_USER_ID = "auth0|saved-policy-view"


@pytest.fixture
def cleanup_engine(disposable_v2_database_url) -> Iterator[Engine]:
    engine = create_engine(disposable_v2_database_url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def previous_release_statements() -> list[str]:
    """Every statement on saved policies, as sent with the earlier table name."""
    return []


@pytest.fixture
def sessions(
    managed_v2_roles, v2_engine_as_role, cleanup_engine, previous_release_statements
) -> Iterator[sessionmaker[Session]]:
    """Open sessions as the runtime role that name saved policies as before.

    Each statement that names ``user_policy_associations`` is sent naming
    ``user_policies`` instead. Results are matched to columns by position, so
    the rewritten labels do not matter.
    """
    runtime_engine = v2_engine_as_role(managed_v2_roles.runtime)

    @event.listens_for(runtime_engine, "before_cursor_execute", retval=True)
    def name_saved_policies_as_before_the_rename(
        _connection, _cursor, statement, parameters, _context, _executemany
    ):
        if RENAMED_TABLE_REFERENCE.search(statement):
            statement = RENAMED_TABLE_REFERENCE.sub(TABLE_BEFORE_THE_RENAME, statement)
            previous_release_statements.append(statement)
        return statement, parameters

    factory = sessionmaker(runtime_engine, class_=Session, expire_on_commit=False)
    issuer = f"https://saved-policy-view-{uuid4().hex[:12]}.example.test/"
    factory.kw["info"] = {"issuer": issuer, "browser_user_ids": []}
    try:
        yield factory
    finally:
        with cleanup_engine.begin() as connection:
            owned = select(UserIdentity.user_id).where(UserIdentity.issuer == issuer)
            user_ids = [
                *connection.execute(owned).scalars(),
                *factory.kw["info"]["browser_user_ids"],
            ]
            if user_ids:
                connection.execute(delete(User).where(User.id.in_(user_ids)))
        runtime_engine.dispose()


def _browser(sessions) -> UnauthenticatedPrincipal:
    user_id = uuid4()
    sessions.kw["info"]["browser_user_ids"].append(user_id)
    return UnauthenticatedPrincipal(user_id=user_id)


def _saved_policy_row(cleanup_engine, association_id: UUID) -> dict | None:
    with cleanup_engine.connect() as connection:
        row = (
            connection.execute(
                text(f"SELECT * FROM {TABLE_AFTER_THE_RENAME} WHERE id = :id"),
                {"id": association_id},
            )
            .mappings()
            .one_or_none()
        )
    return None if row is None else dict(row)


def _statement_kinds(statements: list[str]) -> set[str]:
    """Return the kind of each statement: its first word."""
    return {statement.split(maxsplit=1)[0].upper() for statement in statements}


def test_runtime_role_holds_its_saved_policy_privileges_on_the_view(
    sessions, managed_v2_roles
) -> None:
    with sessions() as session:
        held = {
            privilege: session.execute(
                text("SELECT has_table_privilege(:role, :view, :privilege)"),
                {
                    "role": managed_v2_roles.runtime,
                    "view": f"public.{TABLE_BEFORE_THE_RENAME}",
                    "privilege": privilege,
                },
            ).scalar_one()
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE")
        }

    assert held == dict.fromkeys(("SELECT", "INSERT", "UPDATE", "DELETE"), True)


def test_previous_release_saves_reads_renames_and_deletes_through_the_view(
    sessions, cleanup_engine, previous_release_statements
) -> None:
    browser = _browser(sessions)
    policies = V2UserPolicyService(
        UserPolicyDatabaseSession(sessions), default_legacy_references()
    )

    created = policies.create_user_policy(
        principal=browser,
        association_input=UserPolicyCreateFields(
            country_id="us", legacy_policy_id=1, name="Saved"
        ),
    )
    stored_after_create = _saved_policy_row(cleanup_engine, created.id)
    read = policies.get_user_policy(
        principal=browser, country_id="us", association_id=created.id
    )
    page = policies.list_user_policies(principal=browser, country_id="us")
    renamed = policies.patch_user_policy(
        principal=browser,
        country_id="us",
        association_id=created.id,
        association_input=UserPolicyUpdateInput(name="Renamed"),
    )
    stored_after_rename = _saved_policy_row(cleanup_engine, created.id)
    policies.delete_user_policy(
        principal=browser, country_id="us", association_id=created.id
    )

    assert stored_after_create is not None
    assert stored_after_create["user_id"] == browser.user_id
    assert stored_after_create["created_at"] == created.created_at
    assert read.id == created.id
    assert [association.id for association in page.items] == [created.id]
    assert renamed.name == "Renamed"
    assert stored_after_rename is not None
    assert stored_after_rename["name"] == "Renamed"
    assert _saved_policy_row(cleanup_engine, created.id) is None
    assert _statement_kinds(previous_release_statements) == {
        "INSERT",
        "SELECT",
        "UPDATE",
        "DELETE",
    }


def test_previous_release_merges_saved_policies_and_checks_reports_through_the_view(
    sessions, cleanup_engine, previous_release_statements
) -> None:
    """Sign-in moves a browser's saved policies, and reports name them."""
    browser = _browser(sessions)
    signed_in = UserPrincipal(
        issuer=sessions.kw["info"]["issuer"], subject="google-oauth2|view-merge"
    )
    references = default_legacy_references()
    policies = V2UserPolicyService(UserPolicyDatabaseSession(sessions), references)
    reports = V2UserReportService(UserReportDatabaseSession(sessions), references)
    accounts = V2AccountService(AccountDatabaseSession(sessions))

    account_id = accounts.get_account(principal=signed_in, country_id="us").id
    saved = policies.create_user_policy(
        principal=browser,
        association_input=UserPolicyCreateFields(country_id="us", legacy_policy_id=1),
    )
    report = reports.create_user_report(
        principal=browser,
        association_input=UserReportCreateFields(
            country_id="us",
            legacy_report_id=615,
            user_policy_id=saved.id,
            baseline_user_policy_id=saved.id,
        ),
    )
    accounts.upgrade_account(
        principal=signed_in,
        unauthenticated_user_id=browser.user_id,
        country_id="us",
    )
    exported = accounts.export_account(principal=signed_in, country_id="us")

    stored = _saved_policy_row(cleanup_engine, saved.id)
    assert stored is not None
    assert stored["user_id"] == account_id
    assert report.user_policy_id == saved.id
    assert [policy.id for policy in exported.policies] == [saved.id]
    # The sign-in merge moves every saved policy of the browser's user.
    assert any(
        re.match(
            rf"UPDATE {TABLE_BEFORE_THE_RENAME} SET .*\buser_id=.* WHERE "
            rf"{TABLE_BEFORE_THE_RENAME}\.user_id = ",
            statement,
        )
        for statement in previous_release_statements
    )


def _seed_catalog(cleanup_engine) -> tuple[UUID, str]:
    parameter_name = f"gov.saved_policy_view.rate_{uuid4().hex[:8]}"
    with Session(cleanup_engine) as session, session.begin():
        # The policy copy selects the catalog by this model name.
        model = TaxBenefitModel(name="policyengine-us")
        version = TaxBenefitModelVersion(
            model=model,
            version=POLICYENGINE_VERSION,
            current_law_id=1,
            metadata_time_periods=[2026],
        )
        session.add(Parameter(name=parameter_name, tax_benefit_model_version=version))
        session.flush()
        return model.id, parameter_name


def _delete_mirrored_rows(cleanup_engine, model_id: UUID) -> None:
    with cleanup_engine.begin() as connection:
        user_ids = select(LegacyUserMapping.user_id).where(
            LegacyUserMapping.legacy_user_id == MIRRORED_LEGACY_USER_ID
        )
        mirrored_user_ids = connection.execute(user_ids).scalars().all()
        connection.execute(
            delete(LegacyUserMapping).where(
                LegacyUserMapping.legacy_user_id == MIRRORED_LEGACY_USER_ID
            )
        )
        # Deleting the user deletes its saved policies and their v1 mappings.
        connection.execute(delete(User).where(User.id.in_(mirrored_user_ids)))
        policy_ids = select(Policy.id).where(Policy.tax_benefit_model_id == model_id)
        for model in (LegacyPolicyMapping, ParameterValue):
            connection.execute(delete(model).where(model.policy_id.in_(policy_ids)))
        connection.execute(
            delete(Policy).where(Policy.tax_benefit_model_id == model_id)
        )
        version_ids = select(TaxBenefitModelVersion.id).where(
            TaxBenefitModelVersion.model_id == model_id
        )
        connection.execute(
            delete(Parameter).where(
                Parameter.tax_benefit_model_version_id.in_(version_ids)
            )
        )
        connection.execute(
            delete(TaxBenefitModelVersion).where(
                TaxBenefitModelVersion.model_id == model_id
            )
        )
        connection.execute(
            delete(TaxBenefitModel).where(TaxBenefitModel.id == model_id)
        )


def _legacy_saved_policy(reform_label: str) -> LegacyUserPolicySnapshot:
    return LegacyUserPolicySnapshot.model_validate(
        {
            "country_id": "us",
            "legacy_user_policy_id": 901,
            "reform_id": 801,
            "reform_label": reform_label,
            "baseline_id": 1,
            "baseline_label": "Current law",
            "user_id": MIRRORED_LEGACY_USER_ID,
            "year": "2026",
            "geography": "us",
            "dataset": "enhanced_cps_2024",
            "number_of_provisions": 1,
            "api_version": "1.0.0",
            "added_date": 1,
            "updated_date": 2,
            "budgetary_impact": None,
            "type": None,
        }
    )


def test_previous_release_copies_v1_saved_policies_through_the_view(
    sessions, cleanup_engine, previous_release_statements
) -> None:
    """The Stage 10 saved-policy copy inserts and then updates through the view."""
    model_id, parameter_name = _seed_catalog(cleanup_engine)
    reform = LegacyPolicySnapshot(
        country_id="us",
        legacy_policy_id=801,
        label="Ignored legacy label",
        api_version=COUNTRY_PACKAGE_VERSIONS["us"],
        policy_json={parameter_name: {"2026": 0.2}},
        source_policy_hash=f"view-{uuid4().hex}",
    )
    try:
        with sessions.begin() as session:
            first = mirror_legacy_user_policy_in_session(
                session, _legacy_saved_policy("Copied"), reform, source_revision=1
            )
        with sessions.begin() as session:
            second = mirror_legacy_user_policy_in_session(
                session,
                _legacy_saved_policy("Copied again"),
                reform,
                source_revision=2,
                changed_fields=frozenset({"reform_label"}),
            )
        stored = _saved_policy_row(cleanup_engine, first.association_id)
    finally:
        _delete_mirrored_rows(cleanup_engine, model_id)

    assert first.association_created is True
    assert second.association_id == first.association_id
    assert second.association_created is False
    assert stored is not None
    assert stored["name"] == "Copied again"
    assert {"INSERT", "SELECT", "UPDATE"} <= _statement_kinds(
        previous_release_statements
    )
