"""The UK years offered for society-wide (economy) calculations.

The simulation service runs a UK year only from the data year of the UK
dataset to the last year the UK model projects that dataset to, and answers
any other year with ``DATASET_YEAR_UNAVAILABLE``. That last year is
policyengine-uk's ``PROJECTION_END_YEAR``, shortened when the capital gains
projection in the model's parameters ends earlier: the default end year of
policyengine-uk's own ``extend_single_year_dataset``. The Public API asks the
simulation service for the policyengine-uk version it has installed, so
reading the end year from the installed model keeps this list in step with
the model the simulation service runs.
"""

from typing import TYPE_CHECKING

from policyengine_uk.data.economic_assumptions import (
    CGT_INDEX_PATH,
    PROJECTION_END_YEAR,
)

if TYPE_CHECKING:
    from policyengine_core.parameters import ParameterNode

# The year of the data in the UK dataset (microcosm_uk_2024_25). The
# simulation service reads it from the dataset file and refuses earlier years.
UK_DATASET_DATA_YEAR = 2024


def uk_economy_years(parameters: "ParameterNode") -> list[int]:
    """Return each UK year from the dataset's data year to the last projected one."""
    projection = parameters.get_child(CGT_INDEX_PATH).metadata.get("projection", {})
    last_year = min(
        PROJECTION_END_YEAR, int(projection.get("end_year", PROJECTION_END_YEAR))
    )
    return list(range(UK_DATASET_DATA_YEAR, max(UK_DATASET_DATA_YEAR, last_year) + 1))
