"""Exercise the complete Alembic lifecycle against an ephemeral MySQL schema."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from alembic import command
from alembic.config import Config
from sqlalchemy import Integer, String, Text, delete
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column, registry

from policyengine_api.constants import REPO
from policyengine_api.data.v1_models import (
    Household,
    HouseholdMirrorEvent,
    Policy,
)
from policyengine_api.data.v1_sessions import v1_schema_inspector
from policyengine_api.services.household_service import HouseholdService
from policyengine_api.services.policy_service import PolicyService
from scripts.v1_database_migration import (
    DatabaseState,
    database_state,
    upgrade_database,
)
from tests.fixtures.database_sessions import drop_tables
from tests.integration.alembic_version_rows import current_revision

if TYPE_CHECKING:
    import pytest
    from sqlalchemy.orm import Session, sessionmaker

BASELINE_REVISION = "eafc2a547a4e"
PREVIOUS_REVISION = "3d6e8f553ca5"
# The text columns of the question table: LONGTEXT on MySQL.
LONG_TEXT = Text().with_variant(LONGTEXT(), "mysql")

baseline_revision_tables = registry()


@baseline_revision_tables.mapped
class QuestionAtEafc2a547a4e:
    """Production's orphaned ``question`` table, at the baseline revision.

    Fresh baseline schemas don't have it. Revision 01e49b3a056e drops it if it
    exists, and its downgrade creates it, so downgrading to the base leaves it.
    It is on a registry of its own, never in API v1's metadata.
    """

    __tablename__ = "question"

    question_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    question: Mapped[str] = mapped_column(LONG_TEXT)
    answer: Mapped[str | None] = mapped_column(LONG_TEXT)
    policy_id: Mapped[int | None] = mapped_column(Integer)
    country_id: Mapped[str] = mapped_column(String(3))
    subtask: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))


def _alembic_config(database_url: str) -> Config:
    config = Config(str(REPO / "alembic-v1.ini"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def _table_names(sessions: sessionmaker[Session]) -> list[str]:
    return v1_schema_inspector(sessions).get_table_names()


def _drop_question_table(sessions: sessionmaker[Session]) -> None:
    """Drop the orphaned question table if it exists, as on a fresh schema."""
    if QuestionAtEafc2a547a4e.__tablename__ in _table_names(sessions):
        with sessions.begin() as session:
            drop_tables(session, QuestionAtEafc2a547a4e)


def _assert_head_schema(sessions: sessionmaker[Session]) -> None:
    """Check the tables and columns the head revisions add, remove or change."""
    inspector = v1_schema_inspector(sessions)
    table_names = inspector.get_table_names()
    assert "tracers" not in table_names
    reform_impact_columns = {
        column["name"]: column for column in inspector.get_columns("reform_impact")
    }
    assert reform_impact_columns["dataset"]["default"] is None
    assert reform_impact_columns["execution_id"]["nullable"] is False
    assert "mirror_revision" in {
        column["name"] for column in inspector.get_columns("user_policies")
    }
    assert "user_policy_mirror_events" in table_names
    assert "household_mirror_events" in table_names


def test_fresh_upgrade_check_downgrade_and_reupgrade(
    disposable_v1_database_url: str, v1_sessions: sessionmaker[Session]
) -> None:
    config = _alembic_config(disposable_v1_database_url)

    command.downgrade(config, "base")
    _drop_question_table(v1_sessions)
    command.upgrade(config, "head")
    # The schema matches API v1's models (V1Base.metadata), the migration
    # environment's target metadata, column types and server defaults included.
    command.check(config)

    assert current_revision(v1_sessions) is not None
    _assert_head_schema(v1_sessions)

    command.downgrade(config, BASELINE_REVISION)
    assert "question" in _table_names(v1_sessions)

    command.upgrade(config, "head")
    assert current_revision(v1_sessions) is not None
    command.check(config)


def test_pending_upgrade_commits_head_revision(
    monkeypatch: pytest.MonkeyPatch,
    disposable_v1_database_url: str,
    v1_sessions: sessionmaker[Session],
) -> None:
    config = _alembic_config(disposable_v1_database_url)

    try:
        command.downgrade(config, "base")
        _drop_question_table(v1_sessions)
        command.upgrade(config, "head")
        command.downgrade(config, PREVIOUS_REVISION)

        assert "household_mirror_events" not in _table_names(v1_sessions)

        with v1_sessions() as session:
            assert database_state(session) is DatabaseState.PENDING

        with v1_sessions.begin() as session:
            monkeypatch.delenv("ALEMBIC_DATABASE_URL")
            upgrade_database(session, backup_id="test-backup")

        with v1_sessions() as session:
            assert database_state(session) is DatabaseState.HEAD
        command.check(config)

        assert "question" not in _table_names(v1_sessions)
        _assert_head_schema(v1_sessions)
    finally:
        command.upgrade(config, "head")


def test_policy_mirror_snapshot_uses_mysql_json_representation(
    disposable_v1_database_url: str, v1_sessions: sessionmaker[Session]
) -> None:
    command.upgrade(_alembic_config(disposable_v1_database_url), "head")
    service = PolicyService(v1_sessions)
    result = None
    request_policy = {"gov.phase10.mysql_json_rate": {"2026": 0.040940000000000004}}

    try:
        result = service.set_policy(
            "us",
            "Phase 10 MySQL JSON normalization",
            request_policy,
            prepare_for_mirroring=True,
        )
        stored = service.get_policy("us", result.policy_id)

        assert result.snapshot is not None
        assert stored is not None
        assert request_policy != stored.policy_json
        assert result.snapshot.policy_json == stored.policy_json
        assert result.snapshot.policy_json == {
            "gov.phase10.mysql_json_rate": {"2026": 0.04094}
        }
    finally:
        if result is not None:
            with v1_sessions.begin() as session:
                session.execute(
                    delete(Policy).where(
                        Policy.country_id == "us",
                        Policy.id == result.policy_id,
                    )
                )


def test_household_mirror_event_uses_mysql_json_representation(
    monkeypatch: pytest.MonkeyPatch,
    disposable_v1_database_url: str,
    v1_sessions: sessionmaker[Session],
) -> None:
    command.upgrade(_alembic_config(disposable_v1_database_url), "head")
    service = HouseholdService(v1_sessions)
    result = None
    request_household = {
        "people": {"you": {"phase11_mysql_json_rate": 0.040940000000000004}}
    }
    resolved_spm: dict[str, Any] = {
        "forecast_content_sha256": "a" * 64,
        "scenario": "baseline",
        "geography_kind": "national",
        "geography_id": None,
        "county_vintage": "2020",
        "as_of": None,
    }
    # Keep bundle discovery outside this real MySQL JSON and event contract.
    monkeypatch.setattr(
        "policyengine_api.services.household_service.normalize_spm_selection",
        lambda _country_id, _selection: dict(resolved_spm),
    )

    try:
        result = service.create_household(
            "us",
            request_household,
            "Stage 11 MySQL JSON normalization",
            spm=resolved_spm,
            record_mirror_event=True,
        )
        stored = service.get_household("us", result.household.id)

        assert result.snapshot is not None
        assert stored is not None
        assert request_household != stored.household_json
        assert result.snapshot.household_json == stored.household_json
        assert result.snapshot.household_json == {
            "people": {"you": {"phase11_mysql_json_rate": 0.04094}},
            "spm": resolved_spm,
        }
        with v1_sessions() as session:
            event = session.get(HouseholdMirrorEvent, result.mirror_event_id)
            assert event is not None
            pending = service._decode_mirror_event(event)
        assert pending.snapshot == result.snapshot
    finally:
        if result is not None:
            with v1_sessions.begin() as session:
                session.execute(
                    delete(HouseholdMirrorEvent).where(
                        HouseholdMirrorEvent.country_id == "us",
                        HouseholdMirrorEvent.legacy_household_id == result.household.id,
                    )
                )
                session.execute(
                    delete(Household).where(
                        Household.country_id == "us",
                        Household.id == result.household.id,
                    )
                )
