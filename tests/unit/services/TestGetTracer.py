import pytest
import json
from policyengine_api.services.tracer_analysis_service import (
    TracerAnalysisService,
)
from werkzeug.exceptions import NotFound

from tests.fixtures.services.tracer_fixture_service import (
    test_tracer_data,
    valid_tracer_row,
    valid_tracer,
    
)

tracer_service = TracerAnalysisService()


def test_get_tracer_valid(test_tracer_data):
    # Test get_tracer successfully retrieves valid data from the database.

    result = tracer_service.get_tracer(
        test_tracer_data["country_id"],
        test_tracer_data["household_id"],
        test_tracer_data["policy_id"],
        test_tracer_data["api_version"],
    )

    # match  the valid output as collected from fixture
    valid_output = valid_tracer["tracer_output"]
    assert result == valid_output


def test_get_tracer_not_found():
    # Test get_tracer raises NotFound when no matching record exists.
    data_not_in_db = ["us", "999999", "999", "9.999.0"]
    with pytest.raises(NotFound):
        tracer_service.get_tracer(*data_not_in_db)


def test_get_tracer_database_error(test_db):
    # Test get_tracer handles database errors properly.
    
    values_causing_database_exception = ["us", "1000000", "2", "1.150.0"]
    with pytest.raises(Exception):
        tracer_service.get_tracer(*values_causing_database_exception)