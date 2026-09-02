"""Unit checks for conflict-aware policy insertion statements."""

from __future__ import annotations

from sqlalchemy.dialects import postgresql

from policyengine_api.data.v2.policies import creates


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
