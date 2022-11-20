# `policyengine_api.data`

This module contains the code managing the database used by the main and compute-intensive APIs.

## Tables

### `household`

Stores an individual household's data.

| Column | Type | Description |
| --- | --- | --- |
| `id` | `int` | Unique identifier for the household |
| `label` | `string` | Display name for the household |
| `version` | `string` | Version of the PolicyEngine API when the household was last updated |
| `household_json` | `json` | JSON representation of the household |

Initialisation SQL:

```sql
CREATE TABLE IF NOT EXISTS household (
    id SERIAL PRIMARY KEY,
    label VARCHAR(255) NOT NULL,
    version VARCHAR(255) NOT NULL,
    household_json JSONB NOT NULL
);
```

### `policy`

Stores a policy - a set of time-period-dated parameter overrides from current law.

| Column | Type | Description |
| --- | --- | --- |
| `id` | `int` | Unique identifier for the policy |
| `label` | `string` | Display name for the policy |
| `version` | `string` | Version of the PolicyEngine API when the policy was last updated |
| `policy_json` | `json` | JSON representation of the policy |

Initialisation SQL:

```sql
CREATE TABLE IF NOT EXISTS policy (
    id SERIAL PRIMARY KEY,
    label VARCHAR(255) NOT NULL,
    version VARCHAR(255) NOT NULL,
    policy_json JSONB NOT NULL
);
```

### `economy`

Stores the high-level outputs of a microsimulation run, under a given policy.

| Column | Type | Description |
| --- | --- | --- |
| `household_id` | `int` | Unique identifier for the household |
| `policy_id` | `int` | Unique identifier for the policy |
| `version` | `string` | Version of the PolicyEngine API when the economy was last updated |
| `economy_json` | `json` | JSON representation of the economy |

Initialisation SQL:

```sql
CREATE TABLE IF NOT EXISTS economy (
    household_id INT NOT NULL,
    policy_id INT NOT NULL,
    version VARCHAR(255) NOT NULL,
    economy_json JSONB NOT NULL,
    PRIMARY KEY (household_id, policy_id)
);
```