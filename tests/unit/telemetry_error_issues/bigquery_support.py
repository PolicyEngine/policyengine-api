"""A fake HTTP transport and BigQuery REST API responses."""

from __future__ import annotations

import json

from telemetry_error_issues.transport import HttpResponse

ACCESS_TOKEN = "fake-access-token"


class FakeTransport:
    """Records each HTTP request and answers with queued responses."""

    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.requests: list[object] = []

    def __call__(self, request: object) -> object:
        self.requests.append(request)
        return self.responses.pop(0)

    def json_body(self, index: int) -> dict:
        return json.loads(self.requests[index].body)


def json_response(payload: object, status: int = 200, reason: str = "OK") -> object:
    return HttpResponse(
        status=status, reason=reason, headers={}, body=json.dumps(payload).encode()
    )


def _cell(value: object) -> dict:
    if isinstance(value, list):
        return {"v": [{"v": item} for item in value]}
    return {"v": value}


def query_response(
    fields: list[dict],
    rows: list[list[object]],
    *,
    page_token: str | None = None,
    job_complete: bool = True,
) -> dict:
    response: dict[str, object] = {
        "jobComplete": job_complete,
        "jobReference": {
            "projectId": "policyengine-observability",
            "jobId": "job-1",
            "location": "US",
        },
    }
    if job_complete:
        response["schema"] = {"fields": fields}
        response["rows"] = [{"f": [_cell(value) for value in row]} for row in rows]
    if page_token:
        response["pageToken"] = page_token
    return response


def sent_parameters(transport: FakeTransport, index: int = 0) -> dict:
    return {
        parameter["name"]: parameter
        for parameter in transport.json_body(index)["queryParameters"]
    }
