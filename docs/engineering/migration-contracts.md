# Migration Contracts

Generated from `policyengine_api/migration_registry.py` and `tests/contract/registry.py`.

## Summary

| Metric | Count |
| --- | ---: |
| route group count | 10 |
| workflow count | 7 |
| request count | 14 |
| db entity count | 6 |
| sim flow count | 3 |

## Route Groups

| Route group | Path segments | DB entity | Simulation flow |
| --- | --- | --- | --- |
| `metadata` | `metadata` | `metadata` | `none` |
| `policy` | `policy`, `policies`, `user-policy` | `policy` | `none` |
| `household` | `household`, `calculate`, `calculate-full` | `household` | `household` |
| `economy` | `economy` | `simulation` | `economy` |
| `simulation` | `simulation`, `simulations` | `simulation` | `economy` |
| `report` | `report` | `report` | `report` |
| `user_profile` | `user-profile` | `user` | `none` |
| `simulation_analysis` | `simulation-analysis` | `none` | `none` |
| `tracer_analysis` | `tracer-analysis` | `none` | `none` |
| `ai` | `ai-prompts` | `none` | `none` |

## App V2 Workflow Contracts

### `policy_save_search`

- Current contract: `api_v1_compatible`
- Future owner: PR 10: Policy Migration

| Method | Path | Status | Route group | Stable response fields |
| --- | --- | ---: | --- | --- |
| `POST` | `/us/policy` | 201 | `policy` | `status`, `message`, `result.policy_id` |
| `GET` | `/us/policy/{policy_id}` | 200 | `policy` | `status`, `message`, `result` |
| `GET` | `/us/policies` | 200 | `policy` | `result` |

### `household_save_edit_read`

- Current contract: `api_v1_compatible`
- Future owner: PR 11: Household Migration

| Method | Path | Status | Route group | Stable response fields |
| --- | --- | ---: | --- | --- |
| `POST` | `/us/household` | 201 | `household` | `status`, `message`, `result.household_id` |
| `PUT` | `/us/household/{household_id}` | 200 | `household` | `status`, `message`, `result.household_id` |
| `GET` | `/us/household/{household_id}` | 200 | `household` | `status`, `message`, `result` |

### `household_calculate`

- Current contract: `api_v1_compatible`
- Future owner: PR 13: Household Calculation Compute Cutover

| Method | Path | Status | Route group | Stable response fields |
| --- | --- | ---: | --- | --- |
| `POST` | `/us/calculate` | 200 | `household` | `status`, `message`, `result` |

### `region_selection`

- Current contract: `api_v1_compatible`
- Future owner: PR 9: v2 Metadata, Regions, Datasets, Parameters, and Variables

| Method | Path | Status | Route group | Stable response fields |
| --- | --- | ---: | --- | --- |
| `GET` | `/us/metadata` | 200 | `metadata` | `status`, `result.current_law_id`, `result.economy_options.region`, `result.economy_options.time_period` |
| `GET` | `/uk/metadata` | 200 | `metadata` | `status`, `result.current_law_id`, `result.economy_options.region`, `result.economy_options.time_period` |

### `simulation_submit_poll`

- Current contract: `api_v1_compatible`
- Future owner: PR 13: Household Calculation Compute Cutover

| Method | Path | Status | Route group | Stable response fields |
| --- | --- | ---: | --- | --- |
| `POST` | `/us/simulation` | 201 | `simulation` | `status`, `message`, `result.id`, `result.status` |
| `GET` | `/us/simulation/{simulation_id}` | 200 | `simulation` | `status`, `message`, `result` |

### `report_create_poll`

- Current contract: `api_v1_compatible`
- Future owner: PR 14: Economy Simulation and Economic Impact Compute Cutover

| Method | Path | Status | Route group | Stable response fields |
| --- | --- | ---: | --- | --- |
| `POST` | `/us/report` | 201 | `report` | `status`, `message`, `result.id`, `result.status` |
| `GET` | `/us/report/{report_id}` | 200 | `report` | `status`, `message`, `result` |

### `budget_window_submit_poll`

- Current contract: `api_v1_compatible`
- Future owner: PR 15: Budget-Window and Remaining Simulation API Migration

| Method | Path | Status | Route group | Stable response fields |
| --- | --- | ---: | --- | --- |
| `GET` | `/us/economy/{policy_id}/over/{baseline_policy_id}/budget-window?region=us&start_year=2026&window_size=1` | 200 | `economy` | `status`, `result.kind`, `progress`, `completed_years`, `computing_years`, `queued_years`, `error` |
