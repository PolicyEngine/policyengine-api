from flask import Response
from policyengine_api.utils.payload_validators import validate_country


@validate_country
def foo(country_id, other):
    """
    A simple dummy test method for validation testing. Must be defined outside of the class (or within
    the test functions themselves) due to complications with the `self` parameter for class methods.
    """
    return "bar"


class TestValidateCountry:
    """
    Test that the @validate_country decorator returns 404 if the country does not exist, otherwise
    continues execution of the function.
    """

    def test_valid_country(self):
        result = foo("us", "extra_arg")
        assert result == "bar"

    def test_invalid_country(self):
        result = foo("baz", "extra_arg")
        assert isinstance(result, Response)
        assert result.status_code == 404
