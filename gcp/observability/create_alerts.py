"""Create the initial API v1 Cloud Monitoring alert policies idempotently."""

from __future__ import annotations

import json
import os
import subprocess
import urllib.parse
import urllib.request
from typing import Any

PROJECT = os.environ.get("OBSERVABILITY_PROJECT_ID", "")
API_ROOT = f"https://monitoring.googleapis.com/v3/projects/{PROJECT}"


def _threshold_condition(
    *,
    display_name: str,
    filter_value: str,
    comparison: str,
    threshold: float,
    duration: str,
    alignment_period: str,
    aligner: str,
    reducer: str,
) -> dict[str, Any]:
    return {
        "displayName": display_name,
        "conditionThreshold": {
            "filter": filter_value,
            "comparison": comparison,
            "thresholdValue": threshold,
            "duration": duration,
            "aggregations": [
                {
                    "alignmentPeriod": alignment_period,
                    "perSeriesAligner": aligner,
                    "crossSeriesReducer": reducer,
                }
            ],
            "trigger": {"count": 1},
        },
    }


def _promql_condition(
    *,
    display_name: str,
    query: str,
    duration: str,
    alert_rule: str,
) -> dict[str, Any]:
    return {
        "displayName": display_name,
        "conditionPrometheusQueryLanguage": {
            "query": query,
            "duration": duration,
            "evaluationInterval": "60s",
            "alertRule": alert_rule,
            "ruleGroup": "policyengine_api_v1",
            "disableMetricValidation": True,
        },
    }


def _policy(
    display_name: str,
    condition: dict[str, Any],
    documentation: str,
) -> dict[str, Any]:
    return {
        "displayName": display_name,
        "combiner": "OR",
        "enabled": True,
        "notificationChannels": [],
        "documentation": {
            "content": documentation,
            "mimeType": "text/markdown",
        },
        "alertStrategy": {"autoClose": "1800s"},
        "conditions": [condition],
    }


POLICIES = [
    _policy(
        "API v1 exporter failures",
        _promql_condition(
            display_name="Exporter failure counter increased",
            query=(
                'sum(increase({"policyengine.telemetry.exporter.failure"}[5m])) > 0'
            ),
            duration="0s",
            alert_rule="ExporterFailure",
        ),
        "The API v1 runtime reported at least one telemetry exporter failure.",
    ),
    _policy(
        "API v1 dropped telemetry",
        _promql_condition(
            display_name="Dropped telemetry counter increased",
            query=('sum(increase({"policyengine.telemetry.dropped"}[5m])) > 0'),
            duration="0s",
            alert_rule="DroppedTelemetry",
        ),
        "An API v1 bounded telemetry queue dropped at least one item.",
    ),
    _policy(
        "API v1 elevated error rate",
        _promql_condition(
            display_name="More than one application error in ten minutes",
            query='sum(increase({"policyengine.error.count"}[10m])) > 1',
            duration="0s",
            alert_rule="ElevatedErrorRate",
        ),
        "API v1 application error counters increased more than once in ten minutes.",
    ),
    _policy(
        "API v1 high request latency",
        _promql_condition(
            display_name="P99 request duration above 30 seconds",
            query=(
                "histogram_quantile(0.99, sum by (le) "
                '(rate({"policyengine.request.duration_bucket"}[5m]))) > 30'
            ),
            duration="300s",
            alert_rule="HighRequestLatency",
        ),
        "API v1 P99 request duration exceeded 30 seconds for five minutes.",
    ),
    _policy(
        "API v1 collector unavailable",
        _threshold_condition(
            display_name="Collector Cloud Run service is unhealthy",
            filter_value=(
                'resource.type="cloud_run_revision" AND '
                'metric.type="run.googleapis.com/service_health_count" AND '
                'resource.label."service_name"='
                '"policyengine-api-v1-otel-collector" AND '
                'metric.label."service_health"="UNHEALTHY"'
            ),
            comparison="COMPARISON_GT",
            threshold=0,
            duration="300s",
            alignment_period="60s",
            aligner="ALIGN_MEAN",
            reducer="REDUCE_MAX",
        ),
        "The authenticated API v1 collector reported an unhealthy revision.",
    ),
    _policy(
        "API v1 monthly log ingestion above 10 GiB",
        _threshold_condition(
            display_name="Central analytics bucket exceeds 10 GiB this month",
            filter_value=(
                'resource.type="global" AND '
                'metric.type="logging.googleapis.com/billing/'
                'log_bucket_monthly_bytes_ingested" AND '
                f'metric.label."log_bucket_id"="{PROJECT}"'
            ),
            comparison="COMPARISON_GT",
            threshold=10_737_418_240,
            duration="0s",
            alignment_period="1800s",
            aligner="ALIGN_MAX",
            reducer="REDUCE_SUM",
        ),
        "The central API v1 analytics bucket exceeded 10 GiB of month-to-date ingestion.",
    ),
]


def _token() -> str:
    return subprocess.check_output(
        ["gcloud", "auth", "print-access-token"],
        text=True,
    ).strip()


def _request(
    url: str,
    *,
    token: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def main() -> None:
    if not PROJECT:
        raise SystemExit("Missing deployment variable: OBSERVABILITY_PROJECT_ID")
    token = _token()
    existing: dict[str, str] = {}
    page_token = ""
    while True:
        query = urllib.parse.urlencode({"pageToken": page_token}) if page_token else ""
        suffix = f"?{query}" if query else ""
        response = _request(
            f"{API_ROOT}/alertPolicies{suffix}",
            token=token,
        )
        for policy in response.get("alertPolicies", []):
            existing[str(policy["displayName"])] = str(policy["name"])
        page_token = str(response.get("nextPageToken", ""))
        if not page_token:
            break

    results = []
    for policy in POLICIES:
        display_name = str(policy["displayName"])
        if display_name in existing:
            results.append(
                {
                    "displayName": display_name,
                    "name": existing[display_name],
                    "status": "existing",
                }
            )
            continue
        created = _request(
            f"{API_ROOT}/alertPolicies",
            token=token,
            payload=policy,
        )
        results.append(
            {
                "displayName": display_name,
                "name": created["name"],
                "status": "created",
            }
        )
    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
