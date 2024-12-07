import json
import time
import sqlite3
import pytest

"""
Integration tests for the entire user policy creation lifecycle.
These tests will need to be refactored to not emit against the local database.
"""


class TestUserPolicies:
    # Define the policy to test against
    country_id = "us"
    baseline_id = 2
    baseline_label = "Current law"
    reform_id = 0
    reform_label = "dworkin"
    user_id = 15
    geography = "us"
    dataset = None
    year = "2024"
    number_of_provisions = 3
    api_version = "0.123.45"
    added_date = int(time.time())
    updated_date = int(time.time())
    budgetary_impact = "$13 billion"

    test_policy = {
        "country_id": country_id,
        "baseline_id": baseline_id,
        "baseline_label": baseline_label,
        "reform_id": reform_id,
        "reform_label": reform_label,
        "user_id": user_id,
        "geography": geography,
        "dataset": dataset,
        "year": year,
        "number_of_provisions": number_of_provisions,
        "api_version": api_version,
        "added_date": added_date,
        "updated_date": updated_date,
        "budgetary_impact": budgetary_impact,
    }

    updated_api_version = "0.456.78"
    updated_test_policy = {
        **test_policy,
        "api_version": updated_api_version,
        "updated_date": int(time.time()),
    }

    nulled_test_policy = {
        **test_policy,
        "baseline_label": None,
        "reform_label": None,
    }

    @pytest.fixture(autouse=True)
    def setup_test_db(self, monkeypatch):
        # Create in-memory SQLite database
        def dict_factory(cursor, row):
            d = {}
            for idx, col in enumerate(cursor.description):
                d[col[0]] = row[idx]
            return d

        self.test_conn = sqlite3.connect(":memory:")

        self.test_conn.row_factory = dict_factory

        # Create user_policies table
        self.test_conn.execute(
            """
            CREATE TABLE user_policies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                country_id TEXT,
                baseline_id INTEGER,
                baseline_label TEXT,
                reform_id INTEGER,
                reform_label TEXT,
                user_id INTEGER,
                geography TEXT,
                dataset TEXT,
                year TEXT,
                number_of_provisions INTEGER,
                api_version TEXT,
                added_date INTEGER,
                updated_date INTEGER,
                budgetary_impact TEXT,
                type TEXT
            )
        """
        )

        # Create a test query function that uses our SQLite connection
        def test_query(query, params=None):
            cursor = self.test_conn.cursor()
            try:
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)
                self.test_conn.commit()
                return cursor
            except Exception as e:
                print(f"Query failed: {e}")
                raise e

        # Patch the database.query function
        import policyengine_api.endpoints.policy as policy

        monkeypatch.setattr(policy.database, "query", test_query)

        yield

        # Cleanup
        self.test_conn.close()

    def test_set_and_get_record(self, rest_client):
        # Test POST - first time (create)
        res = rest_client.post("/us/user-policy", json=self.test_policy)
        return_object = json.loads(res.text)
        assert return_object["status"] == "ok"
        assert res.status_code == 201

    def test_get_existing_record(self, rest_client):
        # Insert test data
        self.test_conn.execute(
            """
            INSERT INTO user_policies (
                country_id, baseline_id, baseline_label, reform_id, reform_label,
                user_id, geography, dataset, year, number_of_provisions,
                api_version, added_date, updated_date, budgetary_impact
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.country_id,
                self.baseline_id,
                self.baseline_label,
                self.reform_id,
                self.reform_label,
                self.user_id,
                self.geography,
                self.dataset,
                self.year,
                self.number_of_provisions,
                self.api_version,
                self.added_date,
                self.updated_date,
                self.budgetary_impact,
            ),
        )
        self.test_conn.commit()

        # Test GET
        res = rest_client.get(f"/us/user-policy/{self.user_id}")
        return_object = json.loads(res.text)
        assert return_object["status"] == "ok"
        assert return_object["result"][0]["reform_id"] == self.reform_id
        assert return_object["result"][0]["baseline_id"] == self.baseline_id

    def test_update_record(self, rest_client):
        # Insert test data first
        cursor = self.test_conn.execute(
            """
            INSERT INTO user_policies (
                country_id, baseline_id, baseline_label, reform_id, reform_label,
                user_id, geography, dataset, year, number_of_provisions,
                api_version, added_date, updated_date, budgetary_impact
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                self.country_id,
                self.baseline_id,
                self.baseline_label,
                self.reform_id,
                self.reform_label,
                self.user_id,
                self.geography,
                self.dataset,
                self.year,
                self.number_of_provisions,
                self.api_version,
                self.added_date,
                self.updated_date,
                self.budgetary_impact,
            ),
        )
        user_policy_id = cursor.fetchone()["id"]
        self.test_conn.commit()

        # Test PUT
        updated_test_policy = {
            **self.updated_test_policy,
            "id": user_policy_id,
        }
        res = rest_client.put("/us/user-policy", json=updated_test_policy)
        return_object = json.loads(res.text)
        assert return_object["status"] == "ok"
        assert res.status_code == 200

        # Verify the api_version was updated
        cursor = self.test_conn.execute(
            "SELECT api_version FROM user_policies WHERE id = ?",
            (user_policy_id,),
        )
        row = cursor.fetchone()
        assert row["api_version"] == self.updated_api_version

    def test_nulls_create(self, rest_client):
        # Test POST with null values - first time (create)
        res = rest_client.post("/us/user-policy", json=self.nulled_test_policy)
        return_object = json.loads(res.text)
        assert return_object["status"] == "ok"
        assert res.status_code == 201

    def test_nulls_update(self, rest_client):
        # Insert test data first
        self.test_conn.execute(
            """
            INSERT INTO user_policies (
                country_id, baseline_id, baseline_label, reform_id, reform_label,
                user_id, geography, dataset, year, number_of_provisions,
                api_version, added_date, updated_date, budgetary_impact
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.country_id,
                self.baseline_id,
                None,
                self.reform_id,
                None,
                self.user_id,
                self.geography,
                self.dataset,
                self.year,
                self.number_of_provisions,
                self.api_version,
                self.added_date,
                self.updated_date,
                self.budgetary_impact,
            ),
        )
        self.test_conn.commit()

        # Test POST with null values - second time (update)
        res = rest_client.post("/us/user-policy", json=self.nulled_test_policy)
        return_object = json.loads(res.text)
        assert return_object["status"] == "ok"
        assert res.status_code == 200
