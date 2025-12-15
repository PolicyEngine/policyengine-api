# Bug Report: Entity-Level Aggregation Missing in `build_from_dataframe`

## Summary

The `build_from_dataframe` method in `policyengine_uk` does not aggregate person-level data to entity-level before calling `set_input()`, causing UK country filtering (e.g., Wales) to fail with array length mismatch errors.

## Affected Repository

**Repository:** `policyengine-uk`
**File:** `policyengine_uk/simulation.py`
**Method:** `build_from_dataframe()`
**Approximate Lines:** 281-286 (may vary by version)

## Symptoms

When running a UK simulation filtered to a specific country (e.g., Wales), the following error occurs:

```
ValueError: Unable to set value "[ True  True  True ... False False False]"
for variable "would_evade_tv_licence_fee", as its length is 8470
while there are 4108 households in the simulation.
```

The error occurs because:
- 8,470 = number of Welsh **persons** in the dataset
- 4,108 = number of Welsh **households** in the dataset
- The code tries to assign person-level arrays to household-level variables

## Root Cause

### The Bug Location

```python
# In policyengine_uk/simulation.py, build_from_dataframe method:

# Set input values for each variable and time period
for column in df:
    variable, time_period = column.split("__")
    if variable not in self.tax_benefit_system.variables:
        continue
    self.set_input(variable, time_period, df[column])  # <-- BUG HERE
```

### Why This Fails

1. **`to_input_dataframe()`** exports ALL variables at **person level** (one row per person), regardless of the variable's native entity. This is by design - it creates a flat DataFrame where each row represents a person.

2. **`build_from_dataframe()`** correctly builds the entity structure:
   - Extracts `person_household_id` to determine household membership
   - Creates the correct number of households (e.g., 4,108 for Wales)
   - Sets up person-to-household relationships properly

3. **BUT** the loop that sets variable values does NOT check if aggregation is needed. It passes person-level arrays (8,470 values) directly to `set_input()` for household-level variables that only have 4,108 entities.

### The Correct Approach

The `policyengine_core` library's `build_from_dataset()` method handles this correctly in `policyengine_core/simulations/simulation.py`:

```python
# From policyengine_core/simulations/simulation.py, build_from_dataset method:

if len(data[variable]) != len(population.ids):
    population: GroupPopulation
    entity_level_data = population.value_from_first_person(data[variable])
else:
    entity_level_data = data[variable]

self.set_input(variable_name, time_period, entity_level_data)
```

## Required Fix

### Current Buggy Code

```python
# Set input values for each variable and time period
for column in df:
    variable, time_period = column.split("__")
    if variable not in self.tax_benefit_system.variables:
        continue
    self.set_input(variable, time_period, df[column])
```

### Fixed Code

```python
# Set input values for each variable and time period
for column in df:
    variable, time_period = column.split("__")
    if variable not in self.tax_benefit_system.variables:
        continue

    # Get variable metadata and target population
    var_meta = self.tax_benefit_system.get_variable(variable)
    entity = var_meta.entity
    population = self.get_population(entity.plural)

    data = df[column].values

    # Check if aggregation is needed (data is person-level but variable is group-level)
    if len(data) != population.count:
        # Aggregate from person-level to entity-level using first person's value
        data = population.value_from_first_person(data)

    self.set_input(variable, time_period, data)
```

## Technical Details

### What `value_from_first_person()` Does

This method aggregates person-level data to group-level by taking the value from the first person in each group. For household-level variables (like `would_evade_tv_licence_fee`), all persons in a household share the same value, so taking the first person's value is correct.

The method is defined in `policyengine_core` on `GroupPopulation` objects.

### Why This Pattern Works

- Person-level variables: `len(data) == population.count` (no aggregation needed)
- Group-level variables exported at person level: `len(data) != population.count` (aggregation needed)

### Entity Structure in UK Model

The UK tax-benefit system has these entities:
- `person` - Individual people
- `benunit` - Benefit units (roughly: nuclear families)
- `household` - Households (one or more benefit units sharing accommodation)

When filtering to Wales:
- ~8,470 persons
- ~4,108 households
- Variable ratio depending on household composition

## Reproduction Steps

1. Create a UK macro simulation: `Simulation(country="uk", scope="macro")`
2. Filter to a UK country: `Simulation(country="uk", scope="macro", region="country/wales")`
3. The filtering process:
   - Calls `to_input_dataframe()` on the baseline simulation
   - Filters the DataFrame to Welsh persons only
   - Calls `Microsimulation(dataset=filtered_df)` which invokes `build_from_dataframe()`
4. Error occurs when `build_from_dataframe()` tries to set household-level variables

## Verification

A Jupyter notebook proving this bug exists at:
`policyengine-api/scripts/prove_build_from_dataframe_bug.ipynb`

The notebook:
1. Creates a UK simulation and exports to DataFrame
2. Filters to Wales (8,470 persons, 4,108 households)
3. Manually traces through `build_from_dataframe()` step by step
4. Shows entity structure is correctly built (4,108 households)
5. Demonstrates the `set_input()` call fails with length mismatch
6. Shows the fix (aggregation) works correctly

## Impact

This bug affects:
- UK country filtering (`country/wales`, `country/scotland`, `country/northern_ireland`, `country/england`)
- Any code path that uses `build_from_dataframe()` with a filtered DataFrame

This bug does NOT affect:
- Constituency filtering (uses weight adjustment, not DataFrame subsetting)
- Local authority filtering (uses weight adjustment, not DataFrame subsetting)
- UK-wide simulations (no filtering needed)

## Notes for Implementation

1. The fix is minimal - just wrap the existing `set_input()` call with a length check and aggregation
2. No new dependencies are needed - `value_from_first_person()` is already available on population objects
3. The fix matches the existing pattern in `policyengine_core`'s `build_from_dataset()` method
4. Consider adding a unit test that creates a simulation from a filtered DataFrame and verifies household-level variables work correctly
