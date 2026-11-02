import flask


def test_api_client_does_not_preserve_request_context(api_client):
    assert not flask.has_request_context()

    response = api_client.get("/an-unknown-path")

    assert response.status_code == 404
    assert not flask.has_request_context()
