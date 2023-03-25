import importlib
from flask import Response
import json
from policyengine_core.taxbenefitsystems import TaxBenefitSystem


class PolicyEngineCountry:
    def __init__(self, country_package_name: str):
        self.country_package_name = country_package_name
        self.country_package = importlib.import_module(country_package_name)
        self.tax_benefit_system: TaxBenefitSystem = (
            self.country_package.CountryTaxBenefitSystem()
        )


COUNTRIES = {
    "uk": PolicyEngineCountry("policyengine_uk"),
    "us": PolicyEngineCountry("policyengine_us"),
    "ca": PolicyEngineCountry("policyengine_canada"),
    "ng": PolicyEngineCountry("policyengine_ng"),
}


def validate_country(country_id: str) -> dict:
    if country_id not in COUNTRIES:
        body = dict(
            status="error",
            message=f"Country {country_id} not found. Available countries are: {', '.join(COUNTRIES.keys())}",
        )
        return Response(json.dumps(body), status=404)
    return None
