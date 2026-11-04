# Microdata Weights Skill

Read this before adding code that aggregates simulation microdata: anything
that builds a `MicroSeries` or `MicroDataFrame`, or reads per-household or
per-person columns from an economy result. No module in the package does
today: the last one, the unused economy comparison, has been removed. The
rules below keep new code honest.

## Weights aren't values

A microdata column is one of four kinds, and each allows different operations
(rule `api.microdata.weights-not-values`):

| Kind | Examples | Allowed | Never |
| --- | --- | --- | --- |
| Weight | `household_weight`, `person_weight` | A plain (unweighted) sum, to count entities; use as `weights=` | Aggregation as a value through a weighted series, frame or aggregator |
| Value | `household_net_income`, `person_in_poverty` | Weighted aggregation, with its own entity's weights | Aggregation after the weights are stripped |
| Label | `household_income_decile`, `age`, `is_male`, `race` | Grouping and filtering | Summing or averaging |
| Count | `households`, people per decile | Derived from weights | |

A weighted `MicroSeries` or `MicroDataFrame` weights every `.sum()`, `.mean()`
and `.count()`. Aggregating a weight column that way weights it by itself and
returns the sum of squared weights. In the Simulation API (#766, fixed by
#767), that made `budget.households` about 10^4 times too high on every run,
and its test missed it because it used plain `pd.DataFrame`s.

policyengine's economy outputs arrive as `baseline` and `reform` dicts, whose
microdata columns sit beside their weight columns. Code that builds a
`MicroSeries` from them by hand follows three patterns:

- Values pass `weights=`, and reform values reuse the baseline's weights
  (`weights=baseline_income.weights`).
- Labels (income and wealth deciles, `age`, `is_male`, `race`) are built
  without `weights=` and are only grouping or filter keys.
- Households are counted with a plain sum of `household_weight`.

## Rules

- `api.microdata.weights-not-aggregated-as-values`: a weight is never the value
  of a weighted `MicroSeries`, the variable of a weighted aggregator, or
  `<frame>[<weight>]` followed by a weighted reduction (`sum`, `mean`,
  `median`, `quantile`, `std`, `count`, `groupby`, `cumsum`).
- `api.microdata.weight-stripping-confined`: raw values are read from weighted
  microdata (`np.array`, `np.asarray`, `.values`, `.to_numpy()`, `.tolist()`,
  `pd.DataFrame(...)`, `pd.Series(...)`) only in a designated stripping module.
  Summing stripped values gives an unweighted sample total, the mirror image of
  #767. The Public API has no designated module yet.
- `api.microdata.unweighted-series-are-labels`: a `MicroSeries` built without
  `weights=` is never reduced, so it stays a grouping or filter key.

The guards live in `tests/unit/services/test_microdata_weight_boundaries.py`
and run in `make test`.

## How the guard recognises a weight

The guards read the source, so they recognise names, not types:

- a weight is a string or f-string ending in `_weight` or `_weights` (including
  `f"{entity}_weight"`), a name assigned from one, or a `.weights` attribute;
- weighted microdata is a `MicroSeries` or `MicroDataFrame` built with
  `weights=`, a name assigned from one, anything indexed, filtered or computed
  from those, and, in a module that imports microdf, a string-keyed read from a
  `baseline` or `reform` dict;
- a label is a `MicroSeries` built without `weights=`, or a comparison or
  filter of one.

They don't follow data through function calls or containers, so a weight passed
through a helper or a dict escapes them.

## Handling a finding

Each finding needs a decision, recorded in the PR:

- **Fix it.** Count entities with a plain sum of the weights, aggregate values
  through a weighted series, and reduce the weighted series grouped or filtered
  by a label rather than the label itself.
- **Move it.** A deliberate strip (for example, a per-household quantity used
  only to sort households into buckets) moves into the designated stripping
  module with a comment saying why, and the guard names that module.

All three guards start with no findings and no baseline, so any finding
fails the build until it's decided.
