"""The US years offered for household calculations.

A US household calculation of an SPM measure, such as the SPM poverty
threshold, needs a year that the bundle's certified SPM forecast covers: the
US model answers any other year with ``SPM_YEAR_UNAVAILABLE``. The US household
years are therefore the forecast's years, ending no later than the last year
written in the CPI-U parameter's source file (``gov.bls.cpi.cpi_u``), which is
also the last year policyengine-us projects a dataset to by default. Both
come from the installed model and bundle, so building the list loads no
dataset and runs no simulation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_us.data.economic_assumptions import (
    CPI_U_PARAM_PATH,
    get_parameter_last_year,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from policyengine_core.parameters import ParameterNode


def us_household_years(
    parameters: ParameterNode, forecast_years: Iterable[int]
) -> list[int]:
    """Return the forecast years up to the last CPI-U year, newest first.

    Newest first is the order of the US society-wide years
    (``economy_options.time_period``).
    """
    last_cpi_u_year = get_parameter_last_year(parameters.get_child(CPI_U_PARAM_PATH))
    return sorted(
        {year for year in forecast_years if year <= last_cpi_u_year}, reverse=True
    )
