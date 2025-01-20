import pytest
import json

from policyengine_api.data import PolicyEngineDatabase


# Test the query method using the db's policy table
class TestQuery:
    # Set shared variables
    country_id = "us"
    placeholder = "placeholder"
    first_updated_placeholder = "maxwell"
    second_updated_placeholder = "dworkin"

    # Initialize db connection
    db = PolicyEngineDatabase(local=True, initialize=True)

    # Test INSERT and SELECT statements
    def test_insert(self):
        self.db.query(
            f"INSERT INTO policy (country_id, policy_json, policy_hash, label, api_version) VALUES (?, ?, ?, ?, ?)",
            (
                self.country_id,
                self.placeholder,
                self.placeholder,
                self.placeholder,
                self.placeholder,
            ),
        )

        row = self.db.query(
            f"SELECT * FROM policy WHERE country_id = ? AND policy_json = ? AND policy_hash = ? AND label = ? AND api_version = ?",
            (
                self.country_id,
                self.placeholder,
                self.placeholder,
                self.placeholder,
                self.placeholder,
            ),
        ).fetchone()

        assert row is not None

    # Test INSERT and SELECT statements with None
    def test_insert_null(self):
        self.db.query(
            f"INSERT INTO policy (country_id, policy_json, policy_hash, label, api_version) VALUES (?, ?, ?, ?, ?)",
            (
                self.country_id,
                self.placeholder,
                self.placeholder,
                None,
                self.placeholder,
            ),
        )

        row = self.db.query(
            f"SELECT * FROM policy WHERE country_id = ? AND policy_json = ? AND policy_hash = ? AND label IS NULL AND api_version = ?",
            (
                self.country_id,
                self.placeholder,
                self.placeholder,
                self.placeholder,
            ),
        ).fetchone()

        assert row is not None
        assert row["label"] is None

    # Test UPDATE
    def test_update(self):
        self.db.query(
            f"UPDATE policy SET policy_json = ? WHERE policy_json = ? AND label = ? AND api_version = ? AND country_id = ? AND policy_hash = ? ",
            (
                self.first_updated_placeholder,
                self.placeholder,
                self.placeholder,
                self.placeholder,
                self.country_id,
                self.placeholder,
            ),
        )

        row = self.db.query(
            f"SELECT * FROM policy WHERE country_id = ? AND policy_json = ? AND policy_hash = ? AND label = ? AND api_version = ?",
            (
                self.country_id,
                self.first_updated_placeholder,
                self.placeholder,
                self.placeholder,
                self.placeholder,
            ),
        ).fetchone()

        assert row is not None
        assert row["policy_json"] == self.first_updated_placeholder

    # Test UPDATE with None as search param
    def test_update_none_param(self):
        self.db.query(
            f"UPDATE policy SET policy_json = ? WHERE policy_json = ? AND label IS NULL AND api_version = ? AND country_id = ? AND policy_hash = ? ",
            (
                self.second_updated_placeholder,
                self.placeholder,
                self.placeholder,
                self.country_id,
                self.placeholder,
            ),
        )

        row = self.db.query(
            f"SELECT * FROM policy WHERE country_id = ? AND policy_json = ? AND policy_hash = ? AND label IS NULL AND api_version = ?",
            (
                self.country_id,
                self.second_updated_placeholder,
                self.placeholder,
                self.placeholder,
            ),
        ).fetchone()

        assert row is not None
        assert row["label"] is None
        assert str(row["policy_json"]) == self.second_updated_placeholder

    # Test UPDATE with None as set value
    def test_update_set_none(self):
        self.db.query(
            f"UPDATE policy SET label = ? WHERE policy_json = ? AND api_version = ? AND label = ? AND country_id = ? AND policy_hash = ? ",
            (
                None,
                self.first_updated_placeholder,
                self.placeholder,
                self.placeholder,
                self.country_id,
                self.placeholder,
            ),
        )

        row = self.db.query(
            f"SELECT * FROM policy WHERE country_id = ? AND label IS NULL AND policy_hash = ? AND api_version = ? AND policy_json = ?",
            (
                self.country_id,
                self.placeholder,
                self.placeholder,
                self.first_updated_placeholder,
            ),
        ).fetchone()

        assert row is not None
        assert row["label"] is None

    # Test DELETE
    def test_delete(self):
        # Clean up the first record that was added
        self.db.query(
            f"DELETE FROM policy WHERE policy_json = ? AND label IS NULL AND api_version = ? AND country_id = ? AND policy_hash = ? ",
            (
                self.second_updated_placeholder,
                self.placeholder,
                self.country_id,
                self.placeholder,
            ),
        )

        # Delete the second for testing purposes
        self.db.query(
            f"DELETE FROM policy WHERE label IS NULL AND api_version = ? AND policy_json = ? AND country_id = ? AND policy_hash = ? ",
            (
                self.placeholder,
                self.placeholder,
                self.country_id,
                self.placeholder,
            ),
        )

        # Confirm that it no longer exists
        row = self.db.query(
            f"SELECT * FROM policy WHERE label IS NULL AND country_id = ? AND api_version = ? AND policy_hash = ? AND policy_json = ?",
            (
                self.country_id,
                self.placeholder,
                self.placeholder,
                self.placeholder,
            ),
        ).fetchone()

        assert row is None
