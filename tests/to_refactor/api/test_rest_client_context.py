import flask


def test_rest_client_does_not_preserve_request_context(rest_client):
    assert not flask.has_request_context()

    response = rest_client.get("/readiness-check")

    assert response.status_code == 200
    assert not flask.has_request_context()
