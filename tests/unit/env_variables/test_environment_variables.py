import os
import requests
import pytest

def test_hugging_face_token():
    token = os.getenv("HUGGING_FACE_TOKEN")
    if not token:
        pytest.fail("HUGGING_FACE_TOKEN is not set")

    response = requests.get(
        "https://huggingface.co/api/whoami",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == 200, "Invalid HUGGING_FACE_TOKEN"