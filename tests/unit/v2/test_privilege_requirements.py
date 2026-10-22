"""How the connector analysis decides which privileges a module needs."""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

import pytest

from policyengine_api.data.v2.privilege_requirements import (
    RequiredPrivilege,
    UnclassifiedConnectorError,
    connector_kind,
    required_privileges,
)
from policyengine_api.data.v2.privileges import TablePrivilege

if TYPE_CHECKING:
    from pathlib import Path

TABLE_BY_MODEL = {
    "User": "users",
    "UserPolicy": "user_policy_associations",
    "LegacyPolicyMapping": "legacy_policy_mappings",
}


def _connector(directory: Path, name: str, source: str) -> Path:
    path = directory / name
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    return path


def _needed(path: Path) -> set[tuple[str, TablePrivilege]]:
    return {
        (requirement.table, requirement.privilege)
        for requirement in required_privileges(path, TABLE_BY_MODEL)
    }


@pytest.mark.parametrize(
    ("file_name", "kind"),
    [
        ("reads.py", "reads"),
        ("reads_regions.py", "reads"),
        ("creates.py", "creates"),
        ("updates.py", "updates"),
        ("deletes.py", "deletes"),
    ],
)
def test_module_kind_comes_from_the_file_name(
    tmp_path: Path, file_name: str, kind: str
) -> None:
    assert connector_kind(tmp_path / file_name) == kind


def test_an_unclassified_module_name_is_refused(tmp_path: Path) -> None:
    with pytest.raises(UnclassifiedConnectorError):
        connector_kind(tmp_path / "readers.py")


def test_mutation_modules_also_need_select(tmp_path: Path) -> None:
    path = _connector(
        tmp_path,
        "creates.py",
        """
        from policyengine_api.data.v2.models import UserPolicy

        def create(session, values):
            session.add(UserPolicy(**values))
        """,
    )

    assert _needed(path) == {
        ("user_policy_associations", TablePrivilege.INSERT),
        ("user_policy_associations", TablePrivilege.SELECT),
    }


def test_type_checking_imports_and_annotations_need_nothing(tmp_path: Path) -> None:
    path = _connector(
        tmp_path,
        "reads.py",
        """
        from __future__ import annotations

        from typing import TYPE_CHECKING

        from policyengine_api.data.v2.models import User, UserPolicy

        if TYPE_CHECKING:
            from policyengine_api.data.v2.models import LegacyPolicyMapping

        def read(session, user_id) -> UserPolicy | None:
            return session.get(User, user_id)

        def describe(mapping: LegacyPolicyMapping) -> str:
            return str(mapping)
        """,
    )

    assert _needed(path) == {("users", TablePrivilege.SELECT)}


def test_a_row_lock_needs_update_on_the_selected_table_only(tmp_path: Path) -> None:
    path = _connector(
        tmp_path,
        "reads.py",
        """
        from sqlmodel import select

        from policyengine_api.data.v2.models import LegacyPolicyMapping, User

        def read_mapping(session, *, lock):
            statement = select(LegacyPolicyMapping)
            if lock:
                statement = statement.with_for_update()
            return session.exec(statement).one_or_none()

        def read_user(session, user_id):
            return session.get(User, user_id)
        """,
    )

    requirements = required_privileges(path, TABLE_BY_MODEL)

    assert (
        RequiredPrivilege(
            table="legacy_policy_mappings",
            privilege=TablePrivilege.UPDATE,
            connector="reads.py",
            reason="read_mapping locks rows with with_for_update",
        )
        in requirements
    )
    assert ("users", TablePrivilege.UPDATE) not in _needed(path)


def test_a_share_lock_also_needs_update(tmp_path: Path) -> None:
    path = _connector(
        tmp_path,
        "reads.py",
        """
        from sqlmodel import select

        from policyengine_api.data.v2.models import User

        def read_user(session, user_id):
            return session.exec(select(User).with_for_update(read=True)).one()
        """,
    )

    assert ("users", TablePrivilege.UPDATE) in _needed(path)


def test_a_lock_with_of_needs_update_on_the_named_table_only(tmp_path: Path) -> None:
    path = _connector(
        tmp_path,
        "reads.py",
        """
        from sqlmodel import select

        from policyengine_api.data.v2.models import User, UserPolicy

        def read_with_owner(session):
            return session.exec(
                select(UserPolicy).join(User).with_for_update(of=UserPolicy)
            ).all()
        """,
    )

    assert ("user_policy_associations", TablePrivilege.UPDATE) in _needed(path)
    assert ("users", TablePrivilege.UPDATE) not in _needed(path)
