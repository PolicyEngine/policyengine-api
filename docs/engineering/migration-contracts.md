# Migration Contracts

Generated from `policyengine_api/migration_registry.py` and `tests/contract/registry.py`.

## Summary

| Metric | Count |
| --- | ---: |
| route group count | 9 |
| workflow count | 11 |
| request count | 43 |
| db entity count | 6 |
| sim flow count | 3 |

## Route Groups

| Route group | Path segments | DB entity | Simulation flow |
| --- | --- | --- | --- |
| `health` | `health`, `simulation-gateway-check`, `liveness-check`, `readiness-check` | `none` | `none` |
| `specification` | `specification` | `none` | `none` |
| `metadata` | `metadata`, `datasets`, `economy-options`, `parameter-values`, `parameters`, `regions`, `tax-benefit-model-versions`, `tax-benefit-models`, `variables` | `metadata` | `none` |
| `policy` | `policy`, `policies`, `user-policy`, `user-policies` | `policy` | `none` |
| `household` | `household`, `calculate`, `calculate-full` | `household` | `household` |
| `economy` | `economy` | `simulation` | `economy` |
| `simulation` | `simulation`, `simulations` | `simulation` | `economy` |
| `report` | `report` | `report` | `report` |
| `user_profile` | `user-profile` | `user` | `none` |

## App V2 Workflow Contracts

### `policy_save_search`

- Current contract: `api_v1_compatible`
- Future owner: PR 10: Policy Migration

| Method | Path | Status | Route group | Stable response fields |
| --- | --- | ---: | --- | --- |
| `POST` | `/us/policy` | 201 | `policy` | `status`, `message`, `result.policy_id` |
| `GET` | `/us/policy/{policy_id}` | 200 | `policy` | `status`, `message`, `result` |
| `GET` | `/us/policies` | 200 | `policy` | `result` |

### `policy_resources_v2`

- Current contract: `typed_v2_resources`
- Future owner: PR 10: Policy Migration

| Method | Path | Status | Route group | Stable response fields |
| --- | --- | ---: | --- | --- |
| `POST` | `/v2/policies?country_id=us` | 201 | `policy` | `status`, `message`, `result.item.id`, `result.item.country_id`, `result.item.tax_benefit_model_id`, `result.item.parameter_values`, `result.item.created_at`, `result.item.updated_at` |
| `GET` | `/v2/policies/{policy_id}?country_id=us` | 200 | `policy` | `status`, `message`, `result.item.id`, `result.item.country_id`, `result.item.tax_benefit_model_id`, `result.item.parameter_values`, `result.item.created_at`, `result.item.updated_at` |
| `GET` | `/v2/policies?country_id=us` | 200 | `policy` | `status`, `message`, `result.items`, `result.offset`, `result.limit`, `result.has_more` |

### `saved_policy_v1_compatibility`

- Current contract: `api_v1_compatible`
- Future owner: PR 10: Policy Migration

| Method | Path | Status | Route group | Stable response fields |
| --- | --- | ---: | --- | --- |
| `POST` | `/us/user-policy` | 201 | `policy` | `status`, `message`, `result.id`, `result.reform_id`, `result.reform_label`, `result.baseline_id`, `result.user_id` |
| `GET` | `/us/user-policy/{user_id}` | 200 | `policy` | `status`, `message`, `result` |
| `PUT` | `/us/user-policy` | 200 | `policy` | `status`, `message`, `result.id` |

### `user_policy_associations_v2`

- Current contract: `typed_v2_resources`
- Future owner: PR 10: Policy Migration

| Method | Path | Status | Route group | Stable response fields |
| --- | --- | ---: | --- | --- |
| `POST` | `/v2/user-policies?country_id=us` | 201 | `policy` | `status`, `message`, `result.item.id`, `result.item.country_id`, `result.item.user_id`, `result.item.policy_id`, `result.item.name`, `result.item.description`, `result.item.created_at`, `result.item.updated_at` |
| `GET` | `/v2/user-policies/{association_id}?country_id=us` | 200 | `policy` | `status`, `message`, `result.item.id`, `result.item.country_id`, `result.item.user_id`, `result.item.policy_id`, `result.item.name`, `result.item.description`, `result.item.created_at`, `result.item.updated_at` |
| `GET` | `/v2/user-policies?country_id=us&user_id=caller` | 200 | `policy` | `status`, `message`, `result.items`, `result.offset`, `result.limit`, `result.has_more` |
| `PATCH` | `/v2/user-policies/{association_id}?country_id=us` | 200 | `policy` | `status`, `message`, `result.item.id`, `result.item.name`, `result.item.description`, `result.item.updated_at` |
| `DELETE` | `/v2/user-policies/{association_id}?country_id=us` | 204 | `policy` |  |

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

### `metadata_resources_v2_preview`

- Current contract: `typed_v2_resources`
- Future owner: Later metadata read cutover and v2 route-prefix removal

| Method | Path | Status | Route group | Stable response fields |
| --- | --- | ---: | --- | --- |
| `GET` | `/v2/tax-benefit-models?country_id=us` | 200 | `metadata` | `status`, `message`, `result.policyengine_version`, `result.items`, `result.offset`, `result.limit`, `result.has_more` |
| `GET` | `/v2/tax-benefit-model-versions?country_id=us` | 200 | `metadata` | `status`, `message`, `result.policyengine_version`, `result.items`, `result.offset`, `result.limit`, `result.has_more` |
| `GET` | `/v2/variables?country_id=us` | 200 | `metadata` | `status`, `message`, `result.policyengine_version`, `result.items`, `result.offset`, `result.limit`, `result.has_more` |
| `GET` | `/v2/parameters?country_id=us` | 200 | `metadata` | `status`, `message`, `result.policyengine_version`, `result.items`, `result.offset`, `result.limit`, `result.has_more` |
| `GET` | `/v2/parameters/children?country_id=us&parent_path=gov` | 200 | `metadata` | `status`, `message`, `result.policyengine_version`, `result.items`, `result.offset`, `result.limit`, `result.has_more` |
| `GET` | `/v2/parameter-values?country_id=us` | 200 | `metadata` | `status`, `message`, `result.policyengine_version`, `result.items`, `result.offset`, `result.limit`, `result.has_more` |
| `GET` | `/v2/datasets?country_id=us` | 200 | `metadata` | `status`, `message`, `result.policyengine_version`, `result.items`, `result.offset`, `result.limit`, `result.has_more` |
| `GET` | `/v2/regions?country_id=us` | 200 | `metadata` | `status`, `message`, `result.policyengine_version`, `result.items`, `result.offset`, `result.limit`, `result.has_more` |
| `GET` | `/v2/tax-benefit-models/{model_id}?country_id=us` | 200 | `metadata` | `status`, `message`, `result.policyengine_version`, `result.item` |
| `GET` | `/v2/tax-benefit-model-versions/{version_id}?country_id=us` | 200 | `metadata` | `status`, `message`, `result.policyengine_version`, `result.item` |
| `GET` | `/v2/variables/{variable_id}?country_id=us` | 200 | `metadata` | `status`, `message`, `result.policyengine_version`, `result.item` |
| `GET` | `/v2/parameters/{parameter_id}?country_id=us` | 200 | `metadata` | `status`, `message`, `result.policyengine_version`, `result.item` |
| `GET` | `/v2/parameter-values/{value_id}?country_id=us` | 200 | `metadata` | `status`, `message`, `result.policyengine_version`, `result.item` |
| `GET` | `/v2/datasets/{dataset_id}?country_id=us` | 200 | `metadata` | `status`, `message`, `result.policyengine_version`, `result.item` |
| `GET` | `/v2/regions/{region_id}?country_id=us` | 200 | `metadata` | `status`, `message`, `result.policyengine_version`, `result.item` |
| `GET` | `/v2/regions/by-code/state/ca?country_id=us` | 200 | `metadata` | `status`, `message`, `result.policyengine_version`, `result.item` |
| `GET` | `/v2/tax-benefit-models/by-country/us` | 200 | `metadata` | `status`, `message`, `result.policyengine_version`, `result.model`, `result.model_version` |
| `GET` | `/v2/economy-options?country_id=us` | 200 | `metadata` | `status`, `message`, `result.policyengine_version`, `result.current_law_id`, `result.region`, `result.time_period`, `result.datasets` |

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
