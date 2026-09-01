import inspect
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy import func, select
from sqlalchemy.exc import (
    IntegrityError,
    OperationalError,
    SQLAlchemyError,
    TimeoutError as SQLAlchemyTimeoutError,
)

from policyengine_api.data.v1_models import UserPolicy, UserPolicyMirrorEvent
from policyengine_api.data.v2.user_policies.legacy import (
    LegacyUserPolicyPersistenceResult,
)
from policyengine_api.services.user_policy_service import (
    UserPolicyCreateResult,
    UserPolicyMirrorEventIntegrityError,
    UserPolicyPersistenceError,
    UserPolicyService,
    UserPolicyUpdateResult,
)


ROUTE_PATH = (
    Path(__file__).parents[3] / "policyengine_api" / "routes" / "policy_routes.py"
)
APPLICATION_ROOT = Path(__file__).parents[3] / "policyengine_api"


def _values(**overrides):
    values = {
        "country_id": "us",
        "reform_id": 2,
        "reform_label": "Reform",
        "baseline_id": 1,
        "baseline_label": "Current law",
        "user_id": "auth0|one",
        "year": "2026",
        "geography": "us",
        "dataset": "enhanced_cps_2024",
        "number_of_provisions": 3,
        "api_version": "1",
        "added_date": 1,
        "updated_date": 2,
        "budgetary_impact": None,
        "type": None,
    }
    values.update(overrides)
    return values


def test_user_policy_public_methods_do_not_accept_sessions():
    for method_name in (
        "create_or_get_user_policy",
        "list_user_policies",
        "update_user_policy",
    ):
        parameters = inspect.signature(
            getattr(UserPolicyService, method_name)
        ).parameters
        assert "session" not in parameters
        assert "session_factory" not in parameters


def test_policy_routes_do_not_manage_sessions_or_queries():
    source = ROUTE_PATH.read_text(encoding="utf-8")
    assert "get_v1_session_factory" not in source
    assert "from sqlalchemy" not in source
    assert "select(" not in source


@pytest.mark.parametrize(
    ("error", "expected_category", "expected_retryable"),
    (
        (
            SQLAlchemyTimeoutError("credential=timeout-secret"),
            "timeout",
            True,
        ),
        (
            OperationalError(
                "UPDATE private_table SET token=:token",
                {"token": "bound-parameter-secret"},
                RuntimeError("driver-secret"),
            ),
            "unavailable",
            True,
        ),
        (
            IntegrityError(
                "INSERT caller-private-data",
                {"user_id": "caller-private-data"},
                RuntimeError("integrity-secret"),
            ),
            "integrity",
            False,
        ),
        (SQLAlchemyError("database-secret"), "database", False),
        (RuntimeError("unexpected-secret"), "unexpected", False),
    ),
)
def test_saved_policy_service_translates_failures_to_safe_domain_errors(
    error,
    expected_category,
    expected_retryable,
) -> None:
    session_factory = MagicMock()
    session_factory.begin.side_effect = error
    service = UserPolicyService(session_factory)

    with pytest.raises(UserPolicyPersistenceError) as raised:
        service.create_or_get_user_policy(_values())

    assert raised.value.category == expected_category
    assert raised.value.retryable is expected_retryable
    assert str(raised.value) == "Saved-policy persistence failed"


def test_saved_policy_persistence_failure_category_is_allowlisted() -> None:
    with pytest.raises(ValueError):
        UserPolicyPersistenceError("raw-exception-text")  # type: ignore[arg-type]


def test_saved_policy_event_processing_has_only_request_path_callers():
    sources = {
        path.relative_to(APPLICATION_ROOT).as_posix(): path.read_text(encoding="utf-8")
        for path in APPLICATION_ROOT.rglob("*.py")
    }

    assert {
        path
        for path, source in sources.items()
        if ".process_pending_mirror_events(" in source
    } == {"services/user_policy_mirroring.py"}
    assert {
        path
        for path, source in sources.items()
        if "mirror_pending_user_policy_events_after_commit(" in source
    } == {
        "routes/policy_routes.py",
        "services/user_policy_mirroring.py",
    }


def test_create_reuse_list_and_update_user_policy(orm_session_factory):
    service = UserPolicyService(orm_session_factory)

    created = service.create_or_get_user_policy(_values())
    reused = service.create_or_get_user_policy(
        _values(number_of_provisions=99, updated_date=99)
    )
    listed = service.list_user_policies("us", "auth0|one")
    updated = service.update_user_policy(
        "us",
        created.user_policy.id,
        {"reform_label": "Updated", "updated_date": 3},
    )

    assert isinstance(created, UserPolicyCreateResult)
    assert created.created is True
    assert reused.created is False
    assert reused.user_policy.id == created.user_policy.id
    assert reused.snapshot == created.snapshot
    assert len(listed) == 1
    assert isinstance(listed[0], UserPolicy)
    assert isinstance(updated, UserPolicyUpdateResult)
    assert updated.user_policy.reform_label == "Updated"
    assert updated.user_policy.updated_date == 3
    assert updated.snapshot.reform_label == "Updated"
    assert updated.snapshot.updated_date == 3
    assert updated.snapshot.legacy_user_policy_id == created.user_policy.id
    assert updated.changed_fields == frozenset({"reform_label", "updated_date"})


def test_update_user_policy_requires_matching_country(orm_session_factory):
    service = UserPolicyService(orm_session_factory)
    created = service.create_or_get_user_policy(_values(country_id="uk"))

    assert (
        service.update_user_policy(
            "us",
            created.user_policy.id,
            {"reform_label": "Wrong country"},
        )
        is None
    )
    stored = service.list_user_policies("uk", "auth0|one")[0]
    assert stored.reform_label == "Reform"


def test_dual_write_mutations_store_ordered_complete_events_atomically(
    orm_session_factory,
):
    service = UserPolicyService(orm_session_factory)

    created = service.create_or_get_user_policy(
        _values(),
        record_mirror_event=True,
    )
    updated = service.update_user_policy(
        "us",
        created.user_policy.id,
        {"reform_label": None, "updated_date": 3},
        record_mirror_event=True,
    )

    assert created.mirror_revision == 1
    assert updated is not None
    assert updated.mirror_revision == 2
    with orm_session_factory() as session:
        stored = session.get(UserPolicy, created.user_policy.id)
        events = session.scalars(
            select(UserPolicyMirrorEvent).order_by(
                UserPolicyMirrorEvent.source_revision
            )
        ).all()

    assert stored.mirror_revision == 2
    assert [event.source_revision for event in events] == [1, 2]
    assert [event.event_type for event in events] == ["create", "update"]
    assert events[0].payload_json["changed_fields"] == []
    assert events[1].payload_json["changed_fields"] == [
        "reform_label",
        "updated_date",
    ]
    assert events[1].payload_json["snapshot"]["reform_label"] is None
    assert all(len(event.source_fingerprint_sha256) == 64 for event in events)
    assert all(event.processed_at is None for event in events)


def test_event_failure_rolls_back_the_source_mutation(orm_session_factory):
    service = UserPolicyService(orm_session_factory)

    with (
        patch(
            "policyengine_api.services.user_policy_service."
            "fingerprint_legacy_user_policy",
            side_effect=RuntimeError("cannot encode event"),
        ),
        pytest.raises(UserPolicyPersistenceError) as raised,
    ):
        service.create_or_get_user_policy(
            _values(),
            record_mirror_event=True,
        )

    assert raised.value.category == "unexpected"
    assert isinstance(raised.value.__cause__, RuntimeError)
    with orm_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(UserPolicy)) == 0
        assert (
            session.scalar(select(func.count()).select_from(UserPolicyMirrorEvent)) == 0
        )


def test_update_event_failure_rolls_back_the_source_update(orm_session_factory):
    service = UserPolicyService(orm_session_factory)
    created = service.create_or_get_user_policy(_values())

    with (
        patch(
            "policyengine_api.services.user_policy_service."
            "fingerprint_legacy_user_policy",
            side_effect=RuntimeError("cannot encode event"),
        ),
        pytest.raises(UserPolicyPersistenceError) as raised,
    ):
        service.update_user_policy(
            "us",
            created.user_policy.id,
            {"reform_label": "Should roll back"},
            record_mirror_event=True,
        )

    assert raised.value.category == "unexpected"
    assert isinstance(raised.value.__cause__, RuntimeError)
    with orm_session_factory() as session:
        stored = session.get(UserPolicy, created.user_policy.id)
        assert stored.reform_label == "Reform"
        assert stored.mirror_revision == 0
        assert (
            session.scalar(select(func.count()).select_from(UserPolicyMirrorEvent)) == 0
        )


def test_pending_events_process_in_revision_order_and_mark_after_success(
    orm_session_factory,
):
    service = UserPolicyService(orm_session_factory)
    created = service.create_or_get_user_policy(
        _values(),
        record_mirror_event=True,
    )
    updated = service.update_user_policy(
        "us",
        created.user_policy.id,
        {"reform_label": "Second"},
        record_mirror_event=True,
    )
    processed = []
    committed = []

    def process(event):
        processed.append((event.source_revision, event.changed_fields))
        return LegacyUserPolicyPersistenceResult(
            association_id=UUID("00000000-0000-0000-0000-000000000060"),
            policy_id=UUID("00000000-0000-0000-0000-000000000010"),
            association_created=event.source_revision == 1,
            association_updated=event.source_revision == 2,
            mapping_created=event.source_revision == 1,
        )

    def record_source_commit(_session):
        committed.append(("source_commit", len(processed)))

    def record_processed_commit(event, _result):
        committed.append(("completion_callback", event.source_revision))

    sqlalchemy_event.listen(
        orm_session_factory.class_,
        "after_commit",
        record_source_commit,
    )
    try:
        result = service.process_pending_mirror_events(
            "us",
            created.user_policy.id,
            through_revision=updated.mirror_revision,
            processor=process,
            after_processed_commit=record_processed_commit,
        )
    finally:
        sqlalchemy_event.remove(
            orm_session_factory.class_,
            "after_commit",
            record_source_commit,
        )

    assert processed == [
        (1, frozenset()),
        (2, frozenset({"reform_label"})),
    ]
    assert committed == [
        ("source_commit", 1),
        ("completion_callback", 1),
        ("source_commit", 2),
        ("completion_callback", 2),
    ]
    assert result.association_updated is True
    with orm_session_factory() as session:
        events = session.scalars(select(UserPolicyMirrorEvent)).all()
        assert all(event.processed_at is not None for event in events)


def test_failed_processing_retains_the_oldest_pending_event(orm_session_factory):
    service = UserPolicyService(orm_session_factory)
    created = service.create_or_get_user_policy(
        _values(),
        record_mirror_event=True,
    )

    with pytest.raises(RuntimeError, match="Supabase unavailable"):
        service.process_pending_mirror_events(
            "us",
            created.user_policy.id,
            through_revision=created.mirror_revision,
            processor=lambda event: (_ for _ in ()).throw(
                RuntimeError("Supabase unavailable")
            ),
        )

    with orm_session_factory() as session:
        event = session.scalar(select(UserPolicyMirrorEvent))
        assert event.processed_at is None


def test_already_processed_request_revision_is_verified_by_idempotent_replay(
    orm_session_factory,
):
    service = UserPolicyService(orm_session_factory)
    created = service.create_or_get_user_policy(
        _values(),
        record_mirror_event=True,
    )
    calls = []

    def process(event):
        calls.append(event.source_revision)
        return LegacyUserPolicyPersistenceResult(
            association_id=UUID("00000000-0000-0000-0000-000000000060"),
            policy_id=UUID("00000000-0000-0000-0000-000000000010"),
            association_created=len(calls) == 1,
            association_updated=False,
            mapping_created=len(calls) == 1,
        )

    service.process_pending_mirror_events(
        "us",
        created.user_policy.id,
        through_revision=created.mirror_revision,
        processor=process,
    )
    replay = service.process_pending_mirror_events(
        "us",
        created.user_policy.id,
        through_revision=created.mirror_revision,
        processor=process,
    )

    assert calls == [1, 1]
    assert replay.association_created is False


def test_corrupt_event_changed_fields_are_rejected(orm_session_factory):
    service = UserPolicyService(orm_session_factory)
    created = service.create_or_get_user_policy(
        _values(),
        record_mirror_event=True,
    )
    with orm_session_factory.begin() as session:
        event = session.scalar(select(UserPolicyMirrorEvent))
        event.event_type = "update"
        event.payload_json = {
            **event.payload_json,
            "changed_fields": ["not_a_mutable_source_field"],
        }

    with pytest.raises(
        UserPolicyMirrorEventIntegrityError,
        match="changed fields are unsupported",
    ):
        service.process_pending_mirror_events(
            "us",
            created.user_policy.id,
            through_revision=created.mirror_revision,
            processor=lambda event: None,
        )
