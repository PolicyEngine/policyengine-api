import json
from policyengine_uk.system import system


class PolicyEngineData:
    policy_table = None
    household_table = None
    policy_economy_table = None
    policy_household_table = None

    def __init__(self):
        self.household_table = {
        }
        self.policy_table = {
            "uk-current-law": {
                "policy": [],
                "country_id": "uk",
                "label": "Current law",
            },
            "uk-mini-budget": {
                "policy": [
                    (
                        "gov.hmrc.income_tax.rates.uk[0].rate",
                        "2022",
                        0.21,
                    ),
                ],
                "label": "Mini-budget",
                "country_id": "uk",
            },
            "uk-raise-basic-rate-1p": {
                "policy": [
                    (
                        "gov.hmrc.income_tax.rates.uk[0].rate",
                        "2022",
                        0.21,
                    ),
                ],
                "label": "Basic rate +1p",
                "country_id": "uk",
            }
        }
        self.economy_policy_table = {}
        self.household_policy_table = {}
        self.household_axis_policy_table = {}

