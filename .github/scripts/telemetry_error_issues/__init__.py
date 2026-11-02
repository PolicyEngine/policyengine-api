"""Report each day's telemetry error groups as GitHub issues.

Each run reads one US Eastern calendar day of error records from the central
Cloud Logging bucket through its linked BigQuery dataset. It groups the records
by a keyed fingerprint, measures each group in production and staging, and
creates or updates one GitHub issue per production error group.

Workflow logs, job summaries and issues in this repository are public. The
script therefore publishes only fingerprints, counts, code-defined names and a
Logs Explorer link, never error messages, stack text or identifiers.

``sync_telemetry_error_issues.py`` beside this package runs ``cli.main``.
"""
