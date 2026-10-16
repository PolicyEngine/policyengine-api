from flask import Response

from policyengine_api.utils.payload_validators import validate_country


@validate_country
def foo(country_id, other):
    """Return "bar"; a stand-in view for exercising the decorator.

    It must be defined outside the class (or within the test functions themselves)
    because the decorator treats the first argument as the country ID, and on a
    method that would be `self`.
    """
    return "bar"


class TestValidateCountry:
    """Tests for the @validate_country decorator.

    The decorator returns a 400 response if the country does not exist, and
    otherwise calls the wrapped function.
    """

    def test_valid_country(self):
        result = foo("us", "extra_arg")
        assert result == "bar"

    def test_invalid_country(self):
        result = foo("baz", "extra_arg")
        assert isinstance(result, Response)
        assert result.status_code == 400
