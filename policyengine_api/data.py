import json


EXAMPLE_UK_HOUSEHOLD = dict(
    people=dict(
        person=dict(
            employment_income={"2022": 30_000},
            age={"2022": 30},
            income_tax={"2022": None},
        )
    ),
    benunits=dict(
        benunit=dict(
            adults=["person"],
        ),
    ),
    households=dict(
        household=dict(
            adults=["person"],
        ),
    ),
)

class PolicyEngineData:
    policy_table = None
    household_table = None
    policy_economy_table = None
    policy_household_table = None

    def __init__(self):
        self.household_table = {
            "uk-single-adult": {
                "household_str": json.dumps(EXAMPLE_UK_HOUSEHOLD),
                "country_id": "uk",
                "label": "Single adult, £30k",
            }
        }
        self.policy_table = {
            "uk-current-law": {
                "policy": [],
                "country_id": "uk",
                "label": "Current law",
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

