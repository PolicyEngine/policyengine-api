# Migration Contracts

Generated from `policyengine_api/migration_registry.py` and `tests/contract/registry.py`.

## Summary

| Metric | Count |
| --- | ---: |
| route group count | 9 |
| workflow count | 18 |
| request count | 93 |
| db entity count | 6 |
| sim flow count | 3 |

## Route Groups

| Route group | Path segments | DB entity | Simulation flow |
| --- | --- | --- | --- |
| `health` | `health`, `simulation-gateway-check`, `liveness-check`, `readiness-check` | `none` | `none` |
| `specification` | `specification` | `none` | `none` |
| `metadata` | `metadata`, `countries`, `datasets`, `economy-options`, `parameter-values`, `parameters`, `regions`, `tax-benefit-model-versions`, `tax-benefit-models`, `variables` | `metadata` | `none` |
| `policy` | `policy`, `policies`, `user-policy`, `user-policies` | `policy` | `none` |
| `household` | `household`, `households`, `user-household`, `user-households`, `calculate`, `calculate-full` | `household` | `household` |
| `economy` | `economy` | `simulation` | `economy` |
| `simulation` | `simulation`, `simulations`, `user-simulations` | `simulation` | `economy` |
| `report` | `report`, `reports`, `user-reports`, `shared-reports` | `report` | `report` |
| `user_profile` | `user-profile`, `me` | `user` | `none` |

## App V2 Workflow Contracts

### `policy_save_search`

- Current contract: `api_v1_compatible`
- Future owner: PR 10: Policy Migration

| Method | Path | Status | Route group | Required headers | Stable response fields |
| --- | --- | ---: | --- | --- | --- |
| `POST` | `/us/policy` | 201 | `policy` | none | `status`, `message`, `result.policy_id` |
| `GET` | `/us/policy/{policy_id}` | 200 | `policy` | none | `status`, `message`, `result` |
| `GET` | `/us/policies` | 200 | `policy` | none | `result` |

### `policy_resources_v2`

- Current contract: `typed_v2_resources`
- Future owner: PR 10: Policy Migration

| Method | Path | Status | Route group | Required headers | Stable response fields |
| --- | --- | ---: | --- | --- | --- |
| `POST` | `/v2/policies?country_id=us` | 201 | `policy` | none | `status`, `message`, `result.item.id`, `result.item.country_id`, `result.item.tax_benefit_model_id`, `result.item.parameter_values`, `result.item.created_at`, `result.item.updated_at` |
| `GET` | `/v2/policies/{policy_id}?country_id=us` | 200 | `policy` | none | `status`, `message`, `result.item.id`, `result.item.country_id`, `result.item.tax_benefit_model_id`, `result.item.parameter_values`, `result.item.created_at`, `result.item.updated_at` |
| `GET` | `/v2/policies?country_id=us` | 200 | `policy` | none | `status`, `message`, `result.items`, `result.offset`, `result.limit`, `result.has_more` |

### `saved_policy_v1_compatibility`

- Current contract: `api_v1_compatible`
- Future owner: PR 10: Policy Migration

| Method | Path | Status | Route group | Required headers | Stable response fields |
| --- | --- | ---: | --- | --- | --- |
| `POST` | `/us/user-policy` | 201 | `policy` | none | `status`, `message`, `result.id`, `result.reform_id`, `result.reform_label`, `result.baseline_id`, `result.user_id` |
| `GET` | `/us/user-policy/{user_id}` | 200 | `policy` | none | `status`, `message`, `result` |
| `PUT` | `/us/user-policy` | 200 | `policy` | none | `status`, `message`, `result.id` |

### `user_policy_associations_v2`

- Current contract: `typed_v2_resources`
- Future owner: PR 12A: User Login and v1-Anchored User Associations

| Method | Path | Status | Route group | Required headers | Stable response fields |
| --- | --- | ---: | --- | --- | --- |
| `POST` | `/v2/user-policies?country_id=us` | 201 | `policy` | `Authorization` | `status`, `message`, `result.item.id`, `result.item.country_id`, `result.item.user_id`, `result.item.policy_id`, `result.item.legacy_policy_id`, `result.item.name`, `result.item.description`, `result.item.baseline`, `result.item.provenance`, `result.item.created_at`, `result.item.updated_at` |
| `GET` | `/v2/user-policies/{association_id}?country_id=us` | 200 | `policy` | `Authorization` | `status`, `message`, `result.item.id`, `result.item.country_id`, `result.item.user_id`, `result.item.policy_id`, `result.item.legacy_policy_id`, `result.item.name`, `result.item.description`, `result.item.baseline`, `result.item.provenance`, `result.item.created_at`, `result.item.updated_at` |
| `GET` | `/v2/user-policies?country_id=us` | 200 | `policy` | `Authorization` | `status`, `message`, `result.items`, `result.offset`, `result.limit`, `result.has_more` |
| `PATCH` | `/v2/user-policies/{association_id}?country_id=us` | 200 | `policy` | `Authorization` | `status`, `message`, `result.item.id`, `result.item.legacy_policy_id`, `result.item.policy_id`, `result.item.name`, `result.item.description`, `result.item.baseline`, `result.item.provenance`, `result.item.updated_at` |
| `DELETE` | `/v2/user-policies/{association_id}?country_id=us` | 204 | `policy` | `Authorization` |  |
| `POST` | `/v2/user-policies?country_id=us` | 201 | `policy` | `PolicyEngine-Unauthenticated-User` | `status`, `message`, `result.item.id`, `result.item.country_id`, `result.item.user_id`, `result.item.policy_id`, `result.item.legacy_policy_id`, `result.item.name`, `result.item.description`, `result.item.baseline`, `result.item.provenance`, `result.item.created_at`, `result.item.updated_at` |
| `GET` | `/v2/user-policies/{association_id}?country_id=us` | 200 | `policy` | `PolicyEngine-Unauthenticated-User` | `status`, `message`, `result.item.id`, `result.item.country_id`, `result.item.user_id`, `result.item.policy_id`, `result.item.legacy_policy_id`, `result.item.name`, `result.item.description`, `result.item.baseline`, `result.item.provenance`, `result.item.created_at`, `result.item.updated_at` |
| `GET` | `/v2/user-policies?country_id=us` | 200 | `policy` | `PolicyEngine-Unauthenticated-User` | `status`, `message`, `result.items`, `result.offset`, `result.limit`, `result.has_more` |
| `PATCH` | `/v2/user-policies/{association_id}?country_id=us` | 200 | `policy` | `PolicyEngine-Unauthenticated-User` | `status`, `message`, `result.item.id`, `result.item.legacy_policy_id`, `result.item.policy_id`, `result.item.name`, `result.item.description`, `result.item.baseline`, `result.item.provenance`, `result.item.updated_at` |
| `DELETE` | `/v2/user-policies/{association_id}?country_id=us` | 204 | `policy` | `PolicyEngine-Unauthenticated-User` |  |

### `household_save_read`

- Current contract: `api_v1_compatible`
- Future owner: PR 11: Household Migration

| Method | Path | Status | Route group | Required headers | Stable response fields |
| --- | --- | ---: | --- | --- | --- |
| `POST` | `/us/household` | 201 | `household` | none | `status`, `message`, `result.household_id` |
| `GET` | `/us/household/{household_id}` | 200 | `household` | none | `status`, `message`, `result` |

### `household_resources_v2`

- Current contract: `typed_v2_resources`
- Future owner: PR 11: Household Migration

| Method | Path | Status | Route group | Required headers | Stable response fields |
| --- | --- | ---: | --- | --- | --- |
| `POST` | `/v2/households?country_id=us` | 201 | `household` | none | `status`, `message`, `result.item.id`, `result.item.country_id`, `result.item.default_year`, `result.item.household_data`, `result.item.created_at`, `result.item.updated_at` |
| `GET` | `/v2/households/{household_id}?country_id=us` | 200 | `household` | none | `status`, `message`, `result.item.id`, `result.item.country_id`, `result.item.default_year`, `result.item.household_data`, `result.item.created_at`, `result.item.updated_at` |
| `GET` | `/v2/households?country_id=us` | 200 | `household` | none | `status`, `message`, `result.items`, `result.offset`, `result.limit`, `result.has_more` |

### `user_household_associations_v2`

- Current contract: `typed_v2_resources`
- Future owner: PR 12A: User Login and v1-Anchored User Associations

| Method | Path | Status | Route group | Required headers | Stable response fields |
| --- | --- | ---: | --- | --- | --- |
| `POST` | `/v2/user-households?country_id=us` | 201 | `household` | `Authorization` | `status`, `message`, `result.item.id`, `result.item.country_id`, `result.item.user_id`, `result.item.household_id`, `result.item.legacy_household_id`, `result.item.name`, `result.item.description`, `result.item.created_at`, `result.item.updated_at` |
| `GET` | `/v2/user-households/{association_id}?country_id=us` | 200 | `household` | `Authorization` | `status`, `message`, `result.item.id`, `result.item.country_id`, `result.item.user_id`, `result.item.household_id`, `result.item.legacy_household_id`, `result.item.name`, `result.item.description`, `result.item.created_at`, `result.item.updated_at` |
| `GET` | `/v2/user-households?country_id=us` | 200 | `household` | `Authorization` | `status`, `message`, `result.items`, `result.offset`, `result.limit`, `result.has_more` |
| `PATCH` | `/v2/user-households/{association_id}?country_id=us` | 200 | `household` | `Authorization` | `status`, `message`, `result.item.id`, `result.item.legacy_household_id`, `result.item.household_id`, `result.item.name`, `result.item.description`, `result.item.updated_at` |
| `DELETE` | `/v2/user-households/{association_id}?country_id=us` | 204 | `household` | `Authorization` |  |
| `POST` | `/v2/user-households?country_id=us` | 201 | `household` | `PolicyEngine-Unauthenticated-User` | `status`, `message`, `result.item.id`, `result.item.country_id`, `result.item.user_id`, `result.item.household_id`, `result.item.legacy_household_id`, `result.item.name`, `result.item.description`, `result.item.created_at`, `result.item.updated_at` |
| `GET` | `/v2/user-households/{association_id}?country_id=us` | 200 | `household` | `PolicyEngine-Unauthenticated-User` | `status`, `message`, `result.item.id`, `result.item.country_id`, `result.item.user_id`, `result.item.household_id`, `result.item.legacy_household_id`, `result.item.name`, `result.item.description`, `result.item.created_at`, `result.item.updated_at` |
| `GET` | `/v2/user-households?country_id=us` | 200 | `household` | `PolicyEngine-Unauthenticated-User` | `status`, `message`, `result.items`, `result.offset`, `result.limit`, `result.has_more` |
| `PATCH` | `/v2/user-households/{association_id}?country_id=us` | 200 | `household` | `PolicyEngine-Unauthenticated-User` | `status`, `message`, `result.item.id`, `result.item.legacy_household_id`, `result.item.household_id`, `result.item.name`, `result.item.description`, `result.item.updated_at` |
| `DELETE` | `/v2/user-households/{association_id}?country_id=us` | 204 | `household` | `PolicyEngine-Unauthenticated-User` |  |

### `user_simulation_associations_v2`

- Current contract: `typed_v2_resources`
- Future owner: PR 12A: User Login and v1-Anchored User Associations

| Method | Path | Status | Route group | Required headers | Stable response fields |
| --- | --- | ---: | --- | --- | --- |
| `POST` | `/v2/user-simulations?country_id=us` | 201 | `simulation` | `Authorization` | `status`, `message`, `result.item.id`, `result.item.country_id`, `result.item.user_id`, `result.item.simulation_id`, `result.item.legacy_simulation_id`, `result.item.name`, `result.item.description`, `result.item.created_at`, `result.item.updated_at` |
| `GET` | `/v2/user-simulations/{association_id}?country_id=us` | 200 | `simulation` | `Authorization` | `status`, `message`, `result.item.id`, `result.item.country_id`, `result.item.user_id`, `result.item.simulation_id`, `result.item.legacy_simulation_id`, `result.item.name`, `result.item.description`, `result.item.created_at`, `result.item.updated_at` |
| `GET` | `/v2/user-simulations?country_id=us` | 200 | `simulation` | `Authorization` | `status`, `message`, `result.items`, `result.offset`, `result.limit`, `result.has_more` |
| `PATCH` | `/v2/user-simulations/{association_id}?country_id=us` | 200 | `simulation` | `Authorization` | `status`, `message`, `result.item.id`, `result.item.legacy_simulation_id`, `result.item.name`, `result.item.description`, `result.item.updated_at` |
| `DELETE` | `/v2/user-simulations/{association_id}?country_id=us` | 204 | `simulation` | `Authorization` |  |
| `POST` | `/v2/user-simulations?country_id=us` | 201 | `simulation` | `PolicyEngine-Unauthenticated-User` | `status`, `message`, `result.item.id`, `result.item.country_id`, `result.item.user_id`, `result.item.simulation_id`, `result.item.legacy_simulation_id`, `result.item.name`, `result.item.description`, `result.item.created_at`, `result.item.updated_at` |
| `GET` | `/v2/user-simulations/{association_id}?country_id=us` | 200 | `simulation` | `PolicyEngine-Unauthenticated-User` | `status`, `message`, `result.item.id`, `result.item.country_id`, `result.item.user_id`, `result.item.simulation_id`, `result.item.legacy_simulation_id`, `result.item.name`, `result.item.description`, `result.item.created_at`, `result.item.updated_at` |
| `GET` | `/v2/user-simulations?country_id=us` | 200 | `simulation` | `PolicyEngine-Unauthenticated-User` | `status`, `message`, `result.items`, `result.offset`, `result.limit`, `result.has_more` |
| `PATCH` | `/v2/user-simulations/{association_id}?country_id=us` | 200 | `simulation` | `PolicyEngine-Unauthenticated-User` | `status`, `message`, `result.item.id`, `result.item.legacy_simulation_id`, `result.item.name`, `result.item.description`, `result.item.updated_at` |
| `DELETE` | `/v2/user-simulations/{association_id}?country_id=us` | 204 | `simulation` | `PolicyEngine-Unauthenticated-User` |  |

### `user_report_associations_v2`

- Current contract: `typed_v2_resources`
- Future owner: PR 12A: User Login and v1-Anchored User Associations

| Method | Path | Status | Route group | Required headers | Stable response fields |
| --- | --- | ---: | --- | --- | --- |
| `POST` | `/v2/user-reports?country_id=us` | 201 | `report` | `Authorization` | `status`, `message`, `result.item.id`, `result.item.country_id`, `result.item.user_id`, `result.item.report_id`, `result.item.legacy_report_id`, `result.item.name`, `result.item.description`, `result.item.user_policy_id`, `result.item.baseline_user_policy_id`, `result.item.source_note`, `result.item.provisions`, `result.item.validation`, `result.item.budget_window_years`, `result.item.last_run_at`, `result.item.created_at`, `result.item.updated_at` |
| `GET` | `/v2/user-reports/{association_id}?country_id=us` | 200 | `report` | `Authorization` | `status`, `message`, `result.item.id`, `result.item.country_id`, `result.item.user_id`, `result.item.report_id`, `result.item.legacy_report_id`, `result.item.name`, `result.item.description`, `result.item.user_policy_id`, `result.item.baseline_user_policy_id`, `result.item.source_note`, `result.item.provisions`, `result.item.validation`, `result.item.budget_window_years`, `result.item.last_run_at`, `result.item.created_at`, `result.item.updated_at` |
| `GET` | `/v2/user-reports?country_id=us` | 200 | `report` | `Authorization` | `status`, `message`, `result.items`, `result.offset`, `result.limit`, `result.has_more` |
| `PATCH` | `/v2/user-reports/{association_id}?country_id=us` | 200 | `report` | `Authorization` | `status`, `message`, `result.item.id`, `result.item.legacy_report_id`, `result.item.name`, `result.item.description`, `result.item.user_policy_id`, `result.item.baseline_user_policy_id`, `result.item.source_note`, `result.item.provisions`, `result.item.validation`, `result.item.budget_window_years`, `result.item.last_run_at`, `result.item.updated_at` |
| `DELETE` | `/v2/user-reports/{association_id}?country_id=us` | 204 | `report` | `Authorization` |  |
| `POST` | `/v2/user-reports?country_id=us` | 201 | `report` | `PolicyEngine-Unauthenticated-User` | `status`, `message`, `result.item.id`, `result.item.country_id`, `result.item.user_id`, `result.item.report_id`, `result.item.legacy_report_id`, `result.item.name`, `result.item.description`, `result.item.user_policy_id`, `result.item.baseline_user_policy_id`, `result.item.source_note`, `result.item.provisions`, `result.item.validation`, `result.item.budget_window_years`, `result.item.last_run_at`, `result.item.created_at`, `result.item.updated_at` |
| `GET` | `/v2/user-reports/{association_id}?country_id=us` | 200 | `report` | `PolicyEngine-Unauthenticated-User` | `status`, `message`, `result.item.id`, `result.item.country_id`, `result.item.user_id`, `result.item.report_id`, `result.item.legacy_report_id`, `result.item.name`, `result.item.description`, `result.item.user_policy_id`, `result.item.baseline_user_policy_id`, `result.item.source_note`, `result.item.provisions`, `result.item.validation`, `result.item.budget_window_years`, `result.item.last_run_at`, `result.item.created_at`, `result.item.updated_at` |
| `GET` | `/v2/user-reports?country_id=us` | 200 | `report` | `PolicyEngine-Unauthenticated-User` | `status`, `message`, `result.items`, `result.offset`, `result.limit`, `result.has_more` |
| `PATCH` | `/v2/user-reports/{association_id}?country_id=us` | 200 | `report` | `PolicyEngine-Unauthenticated-User` | `status`, `message`, `result.item.id`, `result.item.legacy_report_id`, `result.item.name`, `result.item.description`, `result.item.user_policy_id`, `result.item.baseline_user_policy_id`, `result.item.source_note`, `result.item.provisions`, `result.item.validation`, `result.item.budget_window_years`, `result.item.last_run_at`, `result.item.updated_at` |
| `DELETE` | `/v2/user-reports/{association_id}?country_id=us` | 204 | `report` | `PolicyEngine-Unauthenticated-User` |  |
| `GET` | `/v2/shared-reports/{association_id}?country_id=us` | 200 | `report` | none | `status`, `message`, `result.item.id`, `result.item.country_id`, `result.item.legacy_report_id`, `result.item.name`, `result.item.source_note`, `result.item.provisions`, `result.item.validation`, `result.item.budget_window_years`, `result.item.baseline_reform`, `result.item.last_run_at`, `result.item.created_at`, `result.item.updated_at` |

### `user_account_v2`

- Current contract: `typed_v2_resources`
- Future owner: PR 12A: User Login and v1-Anchored User Associations

| Method | Path | Status | Route group | Required headers | Stable response fields |
| --- | --- | ---: | --- | --- | --- |
| `GET` | `/v2/me?country_id=us` | 200 | `user_profile` | `Authorization` | `status`, `message`, `result.item.id`, `result.item.user_type`, `result.item.primary_country`, `result.item.first_name`, `result.item.last_name`, `result.item.email`, `result.item.created_at` |
| `GET` | `/v2/me?country_id=us` | 200 | `user_profile` | `PolicyEngine-Unauthenticated-User` | `status`, `message`, `result.item.id`, `result.item.user_type`, `result.item.primary_country`, `result.item.first_name`, `result.item.last_name`, `result.item.email`, `result.item.created_at` |
| `PATCH` | `/v2/me?country_id=us` | 200 | `user_profile` | `Authorization` | `status`, `message`, `result.item.id`, `result.item.primary_country`, `result.item.first_name`, `result.item.last_name` |
| `GET` | `/v2/me/export?country_id=us` | 200 | `user_profile` | `Authorization` | `status`, `message`, `result.user`, `result.policies`, `result.households`, `result.simulations`, `result.reports` |
| `GET` | `/v2/me/export?country_id=us` | 200 | `user_profile` | `PolicyEngine-Unauthenticated-User` | `status`, `message`, `result.user`, `result.policies`, `result.households`, `result.simulations`, `result.reports` |
| `POST` | `/v2/me/upgrade?country_id=us` | 200 | `user_profile` | `Authorization`, `PolicyEngine-Unauthenticated-User` | `status`, `message`, `result.item.id`, `result.item.user_type`, `result.item.primary_country`, `result.outcome` |
| `DELETE` | `/v2/me?country_id=us` | 204 | `user_profile` | `Authorization` |  |
| `DELETE` | `/v2/me?country_id=us` | 204 | `user_profile` | `PolicyEngine-Unauthenticated-User` |  |

### `household_calculate`

- Current contract: `api_v1_compatible`
- Future owner: PR 13: Household Calculation Compute Cutover

| Method | Path | Status | Route group | Required headers | Stable response fields |
| --- | --- | ---: | --- | --- | --- |
| `POST` | `/us/calculate` | 200 | `household` | none | `status`, `message`, `result` |

### `region_selection`

- Current contract: `api_v1_compatible`
- Future owner: PR 9: v2 Metadata, Regions, Datasets, Parameters, and Variables

| Method | Path | Status | Route group | Required headers | Stable response fields |
| --- | --- | ---: | --- | --- | --- |
| `GET` | `/us/metadata` | 200 | `metadata` | none | `status`, `result.current_law_id`, `result.economy_options.region`, `result.economy_options.time_period` |
| `GET` | `/uk/metadata` | 200 | `metadata` | none | `status`, `result.current_law_id`, `result.economy_options.region`, `result.economy_options.time_period` |

### `country_selection_v2`

- Current contract: `typed_v2_resources`
- Future owner: Countries table and one country list in code

| Method | Path | Status | Route group | Required headers | Stable response fields |
| --- | --- | ---: | --- | --- | --- |
| `GET` | `/v2/countries` | 200 | `metadata` | none | `status`, `message`, `result.items` |

### `economy_reports_v2`

- Current contract: `typed_v2_resources`
- Future owner: Economy reports on v2

| Method | Path | Status | Route group | Required headers | Stable response fields |
| --- | --- | ---: | --- | --- | --- |
| `POST` | `/v2/reports?country_id=us` | 201 | `report` | none | `status`, `message`, `result.item.id`, `result.item.country_id`, `result.item.kind`, `result.item.year`, `result.item.baseline_simulation`, `result.item.reform_simulation`, `result.item.status`, `result.item.run`, `result.item.result` |
| `GET` | `/v2/reports/{report_id}?country_id=us` | 200 | `report` | none | `status`, `message`, `result.item.id`, `result.item.legacy_report_id`, `result.item.status`, `result.item.run`, `result.item.result` |
| `GET` | `/v2/reports/by-legacy-number/{legacy_report_id}?country_id=us` | 200 | `report` | none | `status`, `message`, `result.item.id`, `result.item.legacy_report_id`, `result.item.status` |

### `metadata_resources_v2_preview`

- Current contract: `typed_v2_resources`
- Future owner: Later metadata read cutover and v2 route-prefix removal

| Method | Path | Status | Route group | Required headers | Stable response fields |
| --- | --- | ---: | --- | --- | --- |
| `GET` | `/v2/tax-benefit-models?country_id=us` | 200 | `metadata` | none | `status`, `message`, `result.policyengine_version`, `result.items`, `result.offset`, `result.limit`, `result.has_more` |
| `GET` | `/v2/tax-benefit-model-versions?country_id=us` | 200 | `metadata` | none | `status`, `message`, `result.policyengine_version`, `result.items`, `result.offset`, `result.limit`, `result.has_more` |
| `GET` | `/v2/variables?country_id=us` | 200 | `metadata` | none | `status`, `message`, `result.policyengine_version`, `result.items`, `result.offset`, `result.limit`, `result.has_more` |
| `GET` | `/v2/parameters?country_id=us` | 200 | `metadata` | none | `status`, `message`, `result.policyengine_version`, `result.items`, `result.offset`, `result.limit`, `result.has_more` |
| `GET` | `/v2/parameters/children?country_id=us&parent_path=gov` | 200 | `metadata` | none | `status`, `message`, `result.policyengine_version`, `result.items`, `result.offset`, `result.limit`, `result.has_more` |
| `GET` | `/v2/parameter-values?country_id=us` | 200 | `metadata` | none | `status`, `message`, `result.policyengine_version`, `result.items`, `result.offset`, `result.limit`, `result.has_more` |
| `GET` | `/v2/datasets?country_id=us` | 200 | `metadata` | none | `status`, `message`, `result.policyengine_version`, `result.items`, `result.offset`, `result.limit`, `result.has_more` |
| `GET` | `/v2/regions?country_id=us` | 200 | `metadata` | none | `status`, `message`, `result.policyengine_version`, `result.items`, `result.offset`, `result.limit`, `result.has_more` |
| `GET` | `/v2/tax-benefit-models/{model_id}?country_id=us` | 200 | `metadata` | none | `status`, `message`, `result.policyengine_version`, `result.item` |
| `GET` | `/v2/tax-benefit-model-versions/{version_id}?country_id=us` | 200 | `metadata` | none | `status`, `message`, `result.policyengine_version`, `result.item` |
| `GET` | `/v2/variables/{variable_id}?country_id=us` | 200 | `metadata` | none | `status`, `message`, `result.policyengine_version`, `result.item` |
| `GET` | `/v2/parameters/{parameter_id}?country_id=us` | 200 | `metadata` | none | `status`, `message`, `result.policyengine_version`, `result.item` |
| `GET` | `/v2/parameter-values/{value_id}?country_id=us` | 200 | `metadata` | none | `status`, `message`, `result.policyengine_version`, `result.item` |
| `GET` | `/v2/datasets/{dataset_id}?country_id=us` | 200 | `metadata` | none | `status`, `message`, `result.policyengine_version`, `result.item` |
| `GET` | `/v2/regions/{region_id}?country_id=us` | 200 | `metadata` | none | `status`, `message`, `result.policyengine_version`, `result.item` |
| `GET` | `/v2/regions/by-code/state/ca?country_id=us` | 200 | `metadata` | none | `status`, `message`, `result.policyengine_version`, `result.item` |
| `GET` | `/v2/tax-benefit-models/by-country/us` | 200 | `metadata` | none | `status`, `message`, `result.policyengine_version`, `result.model`, `result.model_version` |
| `GET` | `/v2/economy-options?country_id=us` | 200 | `metadata` | none | `status`, `message`, `result.policyengine_version`, `result.current_law_id`, `result.region`, `result.time_period`, `result.datasets` |

### `simulation_submit_poll`

- Current contract: `api_v1_compatible`
- Future owner: PR 13: Household Calculation Compute Cutover

| Method | Path | Status | Route group | Required headers | Stable response fields |
| --- | --- | ---: | --- | --- | --- |
| `POST` | `/us/simulation` | 201 | `simulation` | none | `status`, `message`, `result.id`, `result.status` |
| `GET` | `/us/simulation/{simulation_id}` | 200 | `simulation` | none | `status`, `message`, `result` |

### `report_create_poll`

- Current contract: `api_v1_compatible`
- Future owner: PR 14: Economy Simulation and Economic Impact Compute Cutover

| Method | Path | Status | Route group | Required headers | Stable response fields |
| --- | --- | ---: | --- | --- | --- |
| `POST` | `/us/report` | 201 | `report` | none | `status`, `message`, `result.id`, `result.status` |
| `GET` | `/us/report/{report_id}` | 200 | `report` | none | `status`, `message`, `result` |

### `budget_window_submit_poll`

- Current contract: `api_v1_compatible`
- Future owner: PR 15: Budget-Window and Remaining Simulation API Migration

| Method | Path | Status | Route group | Required headers | Stable response fields |
| --- | --- | ---: | --- | --- | --- |
| `GET` | `/us/economy/{policy_id}/over/{baseline_policy_id}/budget-window?region=us&start_year=2026&window_size=1` | 200 | `economy` | none | `status`, `result.kind`, `progress`, `completed_years`, `computing_years`, `queued_years`, `error` |
