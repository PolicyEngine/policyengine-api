"""The API's country adapter over policyengine-core's example country model.

Route and service tests use it to send households through the API's own situation
parsing into policyengine-core's ``SimulationBuilder``, which builds the axes, without
loading a production country model.
"""

from __future__ import annotations

from dataclasses import replace

from policyengine_core import country_template

from policyengine_api.country import PolicyEngineCountry
from tests.fixtures.spm import household_result_fields

# The example model's variables are mostly monthly, and its default input period
# is January 2022.
TEMPLATE_PERIOD = "2022-01"


def template_household() -> dict:
    """Return two people in one household, with one output variable requested."""
    return {
        "persons": {
            "you": {
                "salary": {TEMPLATE_PERIOD: 1_000},
                "income_tax": {TEMPLATE_PERIOD: None},
            },
            "partner": {"salary": {TEMPLATE_PERIOD: 2_000}},
        },
        "households": {
            "home": {
                "parents": ["you", "partner"],
                "rent": {TEMPLATE_PERIOD: 500},
            },
        },
    }


class TemplateCountry(PolicyEngineCountry):
    """policyengine-core's example country model behind the API's country adapter.

    ``prepare_calculation`` and ``calculate`` are the API's own, so a household's
    axes reach policyengine-core exactly as they do for a production country. The
    example model has no SPM measurement, so the bundle's SPM selection is not
    passed to it, and its results carry the SPM receipt the bundle expects.
    """

    def __init__(self) -> None:
        self.country_package = country_template
        self.tax_benefit_system = country_template.system
        self.metadata = {
            "variables": self.build_variables(),
            "entities": self.build_entities(),
            "parameters": {},
        }

    def _create_simulation(self, household, reform, spm=None):
        return super()._create_simulation(household, reform)

    def calculate(
        self, household, reform, spm=None, *, spm_requested=False, prepared=None
    ):
        calculation = super().calculate(household, reform, prepared=prepared)
        return replace(
            calculation, **household_result_fields(years=[TEMPLATE_PERIOD[:4]])
        )
