import json

from scripts import export_migration_contracts
from scripts.guards import migration_contracts


def test_migration_contract_payload_summarizes_route_contracts():
    payload = export_migration_contracts.build_payload()

    assert payload["version"] == 1
    assert payload["metadata"] == {
        "route_group_count": 10,
        "workflow_count": 7,
        "request_count": 15,
        "db_entity_count": 6,
        "sim_flow_count": 3,
    }
    assert {workflow["name"] for workflow in payload["workflows"]} == {
        "policy_save_search",
        "household_save_edit_read",
        "household_calculate",
        "region_selection",
        "simulation_submit_poll",
        "report_create_poll",
        "budget_window_submit_poll",
    }


def test_generated_migration_contract_json_is_current():
    payload = export_migration_contracts.build_payload()

    assert json.loads(export_migration_contracts.DEFAULT_JSON.read_text()) == payload


def test_generated_migration_contract_markdown_is_current():
    payload = export_migration_contracts.build_payload()

    assert export_migration_contracts.DEFAULT_MARKDOWN.read_text() == (
        export_migration_contracts.render_markdown(payload)
    )


def test_migration_contract_quality_guard_passes():
    assert migration_contracts.check() == []


def test_migration_contract_quality_guard_rejects_duplicate_path_segments(
    monkeypatch,
):
    payload = export_migration_contracts.build_payload()
    duplicate_group = {
        **payload["route_groups"][0],
        "name": "duplicate_metadata",
    }
    monkeypatch.setattr(
        export_migration_contracts,
        "build_payload",
        lambda: {
            **payload,
            "route_groups": [*payload["route_groups"], duplicate_group],
        },
    )

    assert any(
        "duplicate route path segment" in violation
        for violation in migration_contracts.check()
    )
