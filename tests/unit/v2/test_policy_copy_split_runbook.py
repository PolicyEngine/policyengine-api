"""The split command's runbook creates the role the command's grants declare.

C1 · 49's operator creates a temporary role from the runbook's SQL in
``docs/migration/stage-10-v2-policies.md``, so its GRANTs must be exactly the
ones ``POLICY_COPY_SPLIT_PRIVILEGES`` declares.
"""

from __future__ import annotations

import re
from pathlib import Path

from policyengine_api.data.v2.privilege_plans import (
    GrantedPrivileges,
    grant_statements,
    plan_reconciliation,
)
from policyengine_api.data.v2.privileges import (
    POLICY_COPY_SPLIT_PRIVILEGES,
    POLICY_COPY_SPLIT_ROLE,
)

RUNBOOK = Path(__file__).parents[3] / "docs/migration/stage-10-v2-policies.md"
SQL_BLOCK = re.compile(r"```sql\n(.*?)```", re.DOTALL)
TABLE_GRANT = re.compile(r"^\s*(GRANT .+ ON TABLE .+?);?\s*$")


def _runbook_sql_blocks() -> list[str]:
    return SQL_BLOCK.findall(RUNBOOK.read_text(encoding="utf-8"))


def _block_containing(text: str) -> str:
    [block] = [block for block in _runbook_sql_blocks() if text in block]
    return block


def _declared_grants() -> list[str]:
    plan = plan_reconciliation(
        {POLICY_COPY_SPLIT_ROLE: POLICY_COPY_SPLIT_PRIVILEGES},
        GrantedPrivileges(tables={}, columns={}),
        existing_roles={POLICY_COPY_SPLIT_ROLE},
        existing_tables=set(POLICY_COPY_SPLIT_PRIVILEGES),
    )
    return sorted(grant_statements(plan, lambda identifier: identifier))


def test_the_runbook_grants_the_role_exactly_its_declared_privileges() -> None:
    creation = _block_containing(f"CREATE ROLE {POLICY_COPY_SPLIT_ROLE}")

    runbook_grants = sorted(
        match.group(1)
        for statement in creation.splitlines()
        if (match := TABLE_GRANT.match(statement))
    )

    assert runbook_grants == _declared_grants()


def test_the_runbook_creates_a_login_role_with_no_other_powers() -> None:
    creation = _block_containing(f"CREATE ROLE {POLICY_COPY_SPLIT_ROLE}")

    assert (
        f"CREATE ROLE {POLICY_COPY_SPLIT_ROLE} LOGIN NOSUPERUSER NOCREATEDB "
        "NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT PASSWORD"
    ) in creation
    assert f"GRANT USAGE ON SCHEMA public TO {POLICY_COPY_SPLIT_ROLE};" in creation
    assert creation.lstrip().startswith("DO $$")


def test_the_runbook_drops_the_role_and_its_grants() -> None:
    removal = _block_containing(f"DROP ROLE {POLICY_COPY_SPLIT_ROLE}")

    assert f"DROP OWNED BY {POLICY_COPY_SPLIT_ROLE};" in removal
    assert removal.index("DROP OWNED BY") < removal.index("DROP ROLE")
    assert removal.lstrip().startswith("DO $$")
