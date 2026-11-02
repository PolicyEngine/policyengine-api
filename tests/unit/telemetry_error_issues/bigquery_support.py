"""A fake BigQuery client library client, with rows as the library returns them."""

from __future__ import annotations

from google.cloud.bigquery.table import Row

ACCESS_TOKEN = "fake-access-token"


def library_rows(rows: list[dict[str, object]]) -> list[Row]:
    """Return each dictionary as a ``Row``, the type the client library yields."""
    return [
        Row(tuple(row.values()), {name: index for index, name in enumerate(row)})
        for row in rows
    ]


class FakeQueryJob:
    """A finished query job: its result yields the rows, or raises the error."""

    def __init__(
        self, client: FakeBigQueryClient, rows: list[Row], error: Exception | None
    ) -> None:
        self.client = client
        self.rows = rows
        self.error = error

    def result(self, timeout: float | None = None) -> list[Row]:
        self.client.result_timeouts.append(timeout)
        if self.error is not None:
            raise self.error
        return self.rows


class FakeBigQueryClient:
    """Stands in for ``bigquery.Client``, recording each query and its job config.

    Each query returns the rows given for its ``query`` label, or raises
    ``error`` when the test reads its result, as a failed job does.
    """

    def __init__(
        self,
        rows_by_label: dict[str, list[dict[str, object]]] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.rows_by_label = rows_by_label or {}
        self.error = error
        self.created_with: list[tuple[str, str]] = []
        self.queries: list[tuple[str, object]] = []
        self.result_timeouts: list[float | None] = []

    def factory(self, project_id: str, access_token: str) -> FakeBigQueryClient:
        """Replace ``library_client``: record the arguments and return this fake."""
        self.created_with.append((project_id, access_token))
        return self

    def query(self, sql: str, job_config: object) -> FakeQueryJob:
        self.queries.append((sql, job_config))
        rows = self.rows_by_label.get(job_config.labels["query"], [])
        return FakeQueryJob(self, library_rows(rows), self.error)


def sent_parameters(client: FakeBigQueryClient, index: int = 0) -> dict[str, object]:
    """Return the query parameters of the ``index``-th query, by name."""
    _, job_config = client.queries[index]
    return {parameter.name: parameter for parameter in job_config.query_parameters}
