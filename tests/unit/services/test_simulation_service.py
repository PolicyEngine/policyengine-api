import pytest
import json
from unittest.mock import MagicMock, patch
from sqlalchemy.engine.row import LegacyRow

from policyengine_api.services.simulation_service import SimulationService
from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS

from tests.fixtures.services.simulation_fixtures import (
    valid_simulation_data,
    existing_simulation_record,
    duplicate_simulation_data,
)

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
            country_id=valid_simulation_data["country_id"],
            population_id=valid_simulation_data["population_id"],
            population_type=valid_simulation_data["population_type"],
            policy_id=valid_simulation_data["policy_id"],
        )

        # THEN the result should contain the existing simulation
        assert result is not None
        assert result["id"] == existing_simulation_record["id"]
        assert result["country_id"] == valid_simulation_data["country_id"]
        assert (
            result["population_id"] == valid_simulation_data["population_id"]
        )
        assert result["policy_id"] == valid_simulation_data["policy_id"]

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
            country_id=valid_simulation_data["country_id"],
            population_id=valid_simulation_data["population_id"],
            population_type=valid_simulation_data["population_type"],
            policy_id=valid_simulation_data["policy_id"],
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
            "SELECT * FROM simulations WHERE id = ?", (created_simulation["id"],)
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
            "SELECT * FROM simulations WHERE id = ?", (created_simulation["id"],)
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


class TestGetSimulation:
    """Test retrieving simulations from the database."""

    def test_get_simulation_existing(
        self, test_db, existing_simulation_record
    ):
        """Test retrieving an existing simulation."""
        # GIVEN an existing simulation record

        # WHEN we retrieve the simulation
        result = service.get_simulation(
            country_id=valid_simulation_data["country_id"],
            simulation_id=existing_simulation_record["id"],
        )

        # THEN the correct simulation should be returned
        assert result is not None
        assert result["id"] == existing_simulation_record["id"]
        assert result["country_id"] == valid_simulation_data["country_id"]

    def test_get_simulation_nonexistent(self, test_db):
        """Test retrieving a non-existent simulation returns None."""
        # GIVEN an empty database

        # WHEN we try to retrieve a non-existent simulation
        result = service.get_simulation(country_id="us", simulation_id=999)

        # THEN None should be returned
        assert result is None

    def test_get_simulation_wrong_country(
        self, test_db, existing_simulation_record
    ):
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

    def test_duplicate_simulation_raises_error(self, test_db):
        """Test that creating duplicate simulations is prevented by the database."""
        # GIVEN we create a simulation
        service.create_simulation(
            country_id="us",
            population_id="household_123",
            population_type="household",
            policy_id=1,
        )

        # WHEN we try to create an identical simulation
        # THEN it should raise an error due to unique constraint
        with pytest.raises(Exception) as exc_info:
            # Direct database insert to test constraint
            test_db.query(
                """INSERT INTO simulations
                (country_id, api_version, population_id, population_type, policy_id)
                VALUES (?, ?, ?, ?, ?)""",
                ("us", "1.0.0", "household_123", "household", 1),
            )

        # The error should mention the unique constraint
        assert "UNIQUE" in str(exc_info.value).upper()
