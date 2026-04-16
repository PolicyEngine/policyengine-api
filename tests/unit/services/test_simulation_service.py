import pytest
import json

from policyengine_api.services.simulation_service import SimulationService

from tests.fixtures.services import simulation_fixtures

pytest_plugins = ("tests.fixtures.services.simulation_fixtures",)

service = SimulationService()


class TestFindExistingSimulation:
    """Test finding existing simulations in the database."""

    def test_find_existing_simulation_given_existing_record(
        self, test_db, existing_simulation_record
    ):
        """Test that find_existing_simulation returns the existing simulation."""
        # GIVEN an existing simulation record (from fixture)

        # WHEN we search for a simulation with matching parameters
        result = service.find_existing_simulation(
            country_id=simulation_fixtures.valid_simulation_data["country_id"],
            population_id=simulation_fixtures.valid_simulation_data["population_id"],
            population_type=simulation_fixtures.valid_simulation_data[
                "population_type"
            ],
            policy_id=simulation_fixtures.valid_simulation_data["policy_id"],
        )

        # THEN the result should contain the existing simulation
        assert result is not None
        assert result["id"] == existing_simulation_record["id"]
        assert (
            result["country_id"]
            == simulation_fixtures.valid_simulation_data["country_id"]
        )
        assert (
            result["population_id"]
            == simulation_fixtures.valid_simulation_data["population_id"]
        )
        assert (
            result["policy_id"]
            == simulation_fixtures.valid_simulation_data["policy_id"]
        )

    def test_find_existing_simulation_given_no_match(self, test_db):
        """Test that find_existing_simulation returns None when no match exists."""
        # GIVEN an empty database (default test state)

        # WHEN we search for a non-existent simulation
        result = service.find_existing_simulation(
            country_id="uk",
            population_id="nonexistent_123",
            population_type="household",
            policy_id=999,
        )

        # THEN the result should be None
        assert result is None

    def test_find_existing_simulation_ignores_api_version(
        self, test_db, existing_simulation_record
    ):
        """Test that simulations are found regardless of API version."""
        # GIVEN an existing simulation record

        # WHEN we search for the same simulation (API version is ignored)
        result = service.find_existing_simulation(
            country_id=simulation_fixtures.valid_simulation_data["country_id"],
            population_id=simulation_fixtures.valid_simulation_data["population_id"],
            population_type=simulation_fixtures.valid_simulation_data[
                "population_type"
            ],
            policy_id=simulation_fixtures.valid_simulation_data["policy_id"],
        )

        # THEN the existing record should be found (API version ignored)
        assert result is not None
        assert result["id"] == existing_simulation_record["id"]


class TestCreateSimulation:
    """Test creating new simulations in the database."""

    def test_create_simulation_success(self, test_db):
        """Test successful creation of a new simulation."""
        # GIVEN an empty database

        # WHEN we create a new simulation
        created_simulation = service.create_simulation(
            country_id="us",
            population_id="household_123",
            population_type="household",
            policy_id=1,
        )

        # THEN a valid simulation record should be returned
        assert created_simulation is not None
        assert isinstance(created_simulation, dict)
        assert created_simulation["id"] > 0
        assert created_simulation["country_id"] == "us"
        assert created_simulation["population_id"] == "household_123"

        # AND the simulation should be retrievable from database
        result = test_db.query(
            "SELECT * FROM simulations WHERE id = ?",
            (created_simulation["id"],),
        ).fetchone()
        assert result is not None
        assert result["country_id"] == "us"
        assert result["population_id"] == "household_123"

    def test_create_simulation_with_geography_type(self, test_db):
        """Test creating a simulation with geography population type."""
        # GIVEN an empty database

        # WHEN we create a simulation with geography type
        created_simulation = service.create_simulation(
            country_id="uk",
            population_id="geo_code_456",
            population_type="geography",
            policy_id=2,
        )

        # THEN the simulation should be created successfully
        assert created_simulation is not None
        assert created_simulation["population_type"] == "geography"
        result = test_db.query(
            "SELECT * FROM simulations WHERE id = ?",
            (created_simulation["id"],),
        ).fetchone()
        assert result["population_type"] == "geography"

    def test_create_simulation_retrieves_correct_id(self, test_db):
        """Test that create_simulation retrieves the correct ID without race conditions."""
        # GIVEN we create multiple simulations rapidly

        # WHEN we create simulations with different parameters
        created_sims = []
        for i in range(3):
            sim = service.create_simulation(
                country_id="us",
                population_id=f"household_{i}",
                population_type="household",
                policy_id=i,
            )
            created_sims.append(sim)

        # THEN all IDs should be unique and sequential
        ids = [sim["id"] for sim in created_sims]
        assert len(set(ids)) == 3  # All IDs are unique
        assert ids == sorted(ids)  # IDs are in order

        # AND each simulation should have the correct data
        for i, sim in enumerate(created_sims):
            result = test_db.query(
                "SELECT * FROM simulations WHERE id = ?", (sim["id"],)
            ).fetchone()
            assert result["population_id"] == f"household_{i}"
            assert result["policy_id"] == i

    def test_create_simulation_populates_dual_write_state(self, test_db):
        created_simulation = service.create_simulation(
            country_id="us",
            population_id="household_dual_write",
            population_type="household",
            policy_id=3,
        )

        stored_simulation = test_db.query(
            "SELECT * FROM simulations WHERE id = ?",
            (created_simulation["id"],),
        ).fetchone()
        assert stored_simulation["simulation_spec_json"] is not None
        assert stored_simulation["simulation_spec_schema_version"] == 1
        assert stored_simulation["active_run_id"] is not None
        assert stored_simulation["latest_successful_run_id"] is None

        run = test_db.query(
            "SELECT * FROM simulation_runs WHERE simulation_id = ?",
            (created_simulation["id"],),
        ).fetchone()
        assert run is not None
        assert run["status"] == "pending"
        assert run["trigger_type"] == "initial"
        snapshot = run["simulation_spec_snapshot_json"]
        if isinstance(snapshot, str):
            snapshot = json.loads(snapshot)
        assert snapshot["population_id"] == "household_dual_write"
        assert snapshot["policy_id"] == 3

    def test_create_simulation_reuses_existing_row_and_bootstraps_dual_write(
        self, test_db
    ):
        test_db.query(
            """INSERT INTO simulations
            (country_id, api_version, population_id, population_type, policy_id, status)
            VALUES (?, ?, ?, ?, ?, ?)""",
            ("us", "us-system-1.0.0", "household_bootstrap", "household", 7, "pending"),
        )

        created_simulation = service.create_simulation(
            country_id="us",
            population_id="household_bootstrap",
            population_type="household",
            policy_id=7,
        )

        rows = test_db.query(
            """
            SELECT * FROM simulations
            WHERE country_id = ? AND population_id = ? AND population_type = ? AND policy_id = ?
            """,
            ("us", "household_bootstrap", "household", 7),
        ).fetchall()
        assert len(rows) == 1
        assert created_simulation["id"] == rows[0]["id"]

        run = test_db.query(
            "SELECT * FROM simulation_runs WHERE simulation_id = ?",
            (created_simulation["id"],),
        ).fetchone()
        assert run is not None


class TestGetSimulation:
    """Test retrieving simulations from the database."""

    def test_get_simulation_existing(self, test_db, existing_simulation_record):
        """Test retrieving an existing simulation."""
        # GIVEN an existing simulation record

        # WHEN we retrieve the simulation
        result = service.get_simulation(
            country_id=simulation_fixtures.valid_simulation_data["country_id"],
            simulation_id=existing_simulation_record["id"],
        )

        # THEN the correct simulation should be returned
        assert result is not None
        assert result["id"] == existing_simulation_record["id"]
        assert (
            result["country_id"]
            == simulation_fixtures.valid_simulation_data["country_id"]
        )

    def test_get_simulation_nonexistent(self, test_db):
        """Test retrieving a non-existent simulation returns None."""
        # GIVEN an empty database

        # WHEN we try to retrieve a non-existent simulation
        result = service.get_simulation(country_id="us", simulation_id=999)

        # THEN None should be returned
        assert result is None

    def test_get_simulation_wrong_country(self, test_db, existing_simulation_record):
        """Test that simulations are country-specific."""
        # GIVEN an existing simulation for 'us'

        # WHEN we try to retrieve it with a different country
        result = service.get_simulation(
            country_id="uk",  # Wrong country
            simulation_id=existing_simulation_record["id"],
        )

        # THEN None should be returned
        assert result is None

    def test_get_simulation_invalid_id(self, test_db):
        """Test that invalid simulation IDs are handled properly."""
        # GIVEN any database state

        # WHEN we call get_simulation with invalid ID types
        # THEN an exception should be raised
        with pytest.raises(Exception) as exc_info:
            service.get_simulation(country_id="us", simulation_id=-1)
        assert "Invalid simulation ID" in str(exc_info.value)

        with pytest.raises(Exception) as exc_info:
            service.get_simulation(country_id="us", simulation_id="not_an_int")
        assert "Invalid simulation ID" in str(exc_info.value)


class TestUniqueConstraint:
    """Test that the unique constraint on simulations works correctly."""

    def test_duplicate_simulation_returns_existing(self, test_db):
        """Test that creating duplicate simulations returns the existing record."""
        # GIVEN we create a simulation
        first_simulation = service.create_simulation(
            country_id="us",
            population_id="household_123",
            population_type="household",
            policy_id=1,
        )

        # WHEN we try to create an identical simulation
        second_simulation = service.create_simulation(
            country_id="us",
            population_id="household_123",
            population_type="household",
            policy_id=1,
        )

        # THEN the same simulation should be returned (no duplicate created)
        assert first_simulation["id"] == second_simulation["id"]
        assert first_simulation["country_id"] == second_simulation["country_id"]
        assert first_simulation["population_id"] == second_simulation["population_id"]
        assert first_simulation["policy_id"] == second_simulation["policy_id"]


class TestUpdateSimulation:
    def test_update_simulation_updates_dual_write_state(self, test_db):
        created_simulation = service.create_simulation(
            country_id="us",
            population_id="household_update",
            population_type="household",
            policy_id=11,
        )
        output_json = json.dumps({"result": "ok"})

        success = service.update_simulation(
            country_id="us",
            simulation_id=created_simulation["id"],
            status="complete",
            output=output_json,
        )

        assert success is True

        stored_simulation = test_db.query(
            "SELECT * FROM simulations WHERE id = ?",
            (created_simulation["id"],),
        ).fetchone()
        assert stored_simulation["active_run_id"] is None
        assert stored_simulation["latest_successful_run_id"] is not None

        run = test_db.query(
            "SELECT * FROM simulation_runs WHERE simulation_id = ?",
            (created_simulation["id"],),
        ).fetchone()
        assert run["status"] == "complete"
        assert run["output"] == output_json
        assert run["id"] == stored_simulation["latest_successful_run_id"]

    def test_update_simulation_bootstraps_missing_run_state(self, test_db):
        test_db.query(
            """INSERT INTO simulations
            (country_id, api_version, population_id, population_type, policy_id, status)
            VALUES (?, ?, ?, ?, ?, ?)""",
            ("us", "us-system-1.0.0", "household_legacy", "household", 13, "pending"),
        )
        simulation = test_db.query(
            "SELECT * FROM simulations ORDER BY id DESC LIMIT 1"
        ).fetchone()

        success = service.update_simulation(
            country_id="us",
            simulation_id=simulation["id"],
            status="error",
            error_message="legacy failure",
        )

        assert success is True

        stored_simulation = test_db.query(
            "SELECT * FROM simulations WHERE id = ?",
            (simulation["id"],),
        ).fetchone()
        assert stored_simulation["simulation_spec_json"] is not None
        assert stored_simulation["active_run_id"] is None
        assert stored_simulation["latest_successful_run_id"] is None

        run = test_db.query(
            "SELECT * FROM simulation_runs WHERE simulation_id = ?",
            (simulation["id"],),
        ).fetchone()
        assert run is not None
        assert run["status"] == "error"
        assert run["error_message"] == "legacy failure"

    def test_update_simulation_does_not_append_extra_run_for_legacy_patch_traffic(
        self, test_db
    ):
        created_simulation = service.create_simulation(
            country_id="us",
            population_id="household_single_run",
            population_type="household",
            policy_id=14,
        )

        first_run = test_db.query(
            "SELECT * FROM simulation_runs WHERE simulation_id = ?",
            (created_simulation["id"],),
        ).fetchone()
        assert first_run is not None

        success = service.update_simulation(
            country_id="us",
            simulation_id=created_simulation["id"],
            status="complete",
            output=json.dumps({"value": 1}),
        )

        assert success is True

        runs = test_db.query(
            "SELECT * FROM simulation_runs WHERE simulation_id = ? ORDER BY run_sequence",
            (created_simulation["id"],),
        ).fetchall()
        assert len(runs) == 1
        assert runs[0]["id"] == first_run["id"]
        assert runs[0]["status"] == "complete"
