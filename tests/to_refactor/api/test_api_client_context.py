import flask


def test_api_client_does_not_preserve_request_context(api_client):
    assert not flask.has_request_context()

    response = api_client.get("/readiness-check")

    assert response.status_code == 200
    assert not flask.has_request_context()
