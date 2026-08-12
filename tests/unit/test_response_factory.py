from policyengine_api.response_factory import _make_error_response


def test_error_response_factory_builds_standard_json_response():
    response = _make_error_response("Policy #2 not found.", 404)

    assert response.status_code == 404
    assert response.mimetype == "application/json"
    assert response.get_json() == {
        "status": "error",
        "message": "Policy #2 not found.",
    }


def test_error_response_factory_includes_structured_payload_fields():
    response = _make_error_response(
        "Invalid inputs",
        400,
        result=None,
        errors=[{"name": "unknown_variable"}],
    )

    assert response.get_json() == {
        "status": "error",
        "message": "Invalid inputs",
        "result": None,
        "errors": [{"name": "unknown_variable"}],
    }


def test_error_response_factory_can_preserve_message_only_v1_payloads():
    response = _make_error_response(
        "Database error",
        500,
        include_status=False,
    )

    assert response.get_json() == {"message": "Database error"}


def test_error_response_factory_can_preserve_a_legacy_default_mimetype():
    response = _make_error_response("Invalid country", 400, mimetype=None)

    assert response.content_type == "text/html; charset=utf-8"
