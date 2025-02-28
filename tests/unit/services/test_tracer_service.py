import pytest
import json
from policyengine_api.services.tracer_analysis_service import TracerAnalysisService
from werkzeug.exceptions import NotFound

from tests.fixtures.tracer_fixtures import (
    test_tracer_data,
    valid_tracer_row,
    valid_request_body,
    tracer_service
)


def test_get_tracer_valid(tracer_service, test_tracer_data):
    # Test get_tracer successfully retrieves valid data from the database.
    record = test_tracer_data

    result = tracer_service.get_tracer(
        record["country_id"], record["household_id"], record["policy_id"], record["api_version"]
    )
    
    # match  the valid output as collected from fixture
    valid_output = valid_request_body["tracer_output"]
    assert result == valid_output
    

def test_get_tracer_not_found(tracer_service):
    # Test get_tracer raises NotFound when no matching record exists.
    with pytest.raises(NotFound):
        tracer_service.get_tracer("us", "999999", "999", "9.999.0")


def test_get_tracer_database_error(tracer_service, test_db):
    # Test get_tracer handles database errors properly.
    with pytest.raises(Exception):
        tracer_service.get_tracer("us", "71424", "2", "1.150.0")


def test_invalid_input_type(tracer_service , test_db):
    # Test get_tracer handles invalid input parameter error
    with pytest.raises(Exception) as exception_val:
        tracer_service.get_tracer("us" , 100 , "2" , "1.150.0")
    
    if exception_val.type == TypeError:
        assert exception_val.type == TypeError
    else:
        pytest.fail(f"Expected value not found instead {type(exception_val)}")
    
def test_invalid_input_value(tracer_service,test_db):
    # Test get_tracer handles invalid input value error
    
    with pytest.raises(Exception) as exception_val:
        tracer_service.get_tracer("usa" , "-100" , "2" , "1.150.0")
    
    if exception_val.type == ValueError:
        assert exception_val.type == ValueError
    else:
        pytest.fail(f"Expected value not found instead {type(exception_val)}")
    