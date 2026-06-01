from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from fastapi.testclient import TestClient
from flask import Flask

from policyengine_api.asgi_factory import create_asgi_app


@dataclass(frozen=True)
class ContractResponse:
    status_code: int
    body: bytes
    headers: Mapping[str, str]
    content_type: str | None

    @property
    def data(self) -> bytes:
        return self.body


class ContractClient(Protocol):
    def open(
        self,
        path: str,
        *,
        method: str,
        json: dict | None = None,
        headers: dict | None = None,
    ) -> ContractResponse: ...


class FlaskContractClient:
    def __init__(self, app: Flask):
        self._client = app.test_client()

    def open(
        self,
        path: str,
        *,
        method: str,
        json: dict | None = None,
        headers: dict | None = None,
    ) -> ContractResponse:
        response = self._client.open(
            path,
            method=method,
            json=json,
            headers=headers,
        )
        return ContractResponse(
            status_code=response.status_code,
            body=response.data,
            headers=dict(response.headers),
            content_type=response.content_type,
        )


class ASGIContractClient:
    def __init__(self, app: Flask):
        self._client = TestClient(create_asgi_app(app))

    def open(
        self,
        path: str,
        *,
        method: str,
        json: dict | None = None,
        headers: dict | None = None,
    ) -> ContractResponse:
        response = self._client.request(
            method,
            path,
            json=json,
            headers=headers,
        )
        return ContractResponse(
            status_code=response.status_code,
            body=response.content,
            headers=dict(response.headers),
            content_type=response.headers.get("content-type"),
        )
