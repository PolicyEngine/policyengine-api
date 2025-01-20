import pytest
import json
import time
import sqlite3
from policyengine_api.data import database
from policyengine_api.utils import hash_object
from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS


class TestPolicyCreation:
    # Define the policy to test against
    country_id = "us"
    policy_json = {"sample_parameter": {"2024-01-01.2025-12-31": True}}
    label = "dworkin"
    test_policy = {"data": policy_json, "label": label}
    policy_hash = hash_object(policy_json)

    """
    Test creating a policy, then ensure that duplicating
    that policy generates the correct response within the
    app; this requires sequential processing, hence the 
    need for a separate Python-based test
    """

    def test_create_unique_policy(self, rest_client):
        database.query(
            f"DELETE FROM policy WHERE policy_hash = ? AND label = ? AND country_id = ?",
            (self.policy_hash, self.label, self.country_id),
        )

        res = rest_client.post("/us/policy", json=self.test_policy)
        return_object = json.loads(res.text)

        assert return_object["status"] == "ok"
        assert res.status_code == 201

    def test_create_nonunique_policy(self, rest_client):
        res = rest_client.post("/us/policy", json=self.test_policy)
        return_object = json.loads(res.text)

        assert return_object["status"] == "ok"
        assert res.status_code == 200

        database.query(
            f"DELETE FROM policy WHERE policy_hash = ? AND label = ? AND country_id = ?",
            (self.policy_hash, self.label, self.country_id),
        )

    def test_create_policy_invalid_country(self, rest_client):
        res = rest_client.post("/au/policy", json=self.test_policy)
        assert res.status_code == 400


class TestPolicySearch:
    country_id = "us"
    policy_json = {"sample_input": {"2023-01-01.2024-12-31": True}}
    label = "maxwell"
    policy_hash = hash_object(policy_json)
    api_version = COUNTRY_PACKAGE_VERSIONS.get(country_id)

    # Pre-seed database with duplicate policies
    for i in range(2):
        database.query(
            f"INSERT INTO policy (country_id, label, policy_json, policy_hash, api_version) VALUES (?, ?, ?, ?, ?)",
            (
                country_id,
                label,
                json.dumps(policy_json),
                policy_hash,
                api_version,
            ),
        )

    db_output = database.query(
        f"SELECT * FROM policy WHERE label = ?",
        (label,),
    ).fetchall()

    def test_search_all_policies(self, rest_client):
        res = rest_client.get("/us/policies")
        return_object = json.loads(res.text)

        filtered_return = list(
            filter(lambda x: x["label"] == self.label, return_object["result"])
        )

        assert return_object["status"] == "ok"
        assert len(filtered_return) == len(self.db_output)

    def test_search_unique_policies(self, rest_client):
        res = rest_client.get("/us/policies?unique_only=true")
        return_object = json.loads(res.text)

        filtered_return = list(
            filter(lambda x: x["label"] == self.label, return_object["result"])
        )

        assert return_object["status"] == "ok"
        assert len(filtered_return) == 1

        # Clean up duplicate policies created
        database.query(
            f"DELETE FROM policy WHERE policy_hash = ? AND label = ? AND country_id = ?",
            (self.policy_hash, self.label, self.country_id),
        )


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
