from typing import Dict
import json
import traceback
import datetime
import time
import os

from policyengine_api.jobs import BaseJob
from policyengine_api.jobs.tasks import compute_general_economy
from policyengine_api.services.reform_impacts_service import (
    ReformImpactsService,
)
from policyengine_api.endpoints.economy.compare import compare_economic_outputs
from policyengine_api.endpoints.economy.reform_impact import set_comment_on_job
from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.country import COUNTRIES, create_policy_reform
from policyengine_api.utils import WorkerLogger
from policyengine_core.simulations import Microsimulation

from policyengine_us import Microsimulation
from policyengine_uk import Microsimulation

reform_impacts_service = ReformImpactsService()

logger = WorkerLogger()


class CalculateEconomySimulationJob(BaseJob):
    def __init__(self):
        super().__init__()

    def run(
        self,
        baseline_policy_id: int,
        policy_id: int,
        country_id: str,
        region: str,
        dataset: str,
        time_period: str,
        options: dict,
        baseline_policy: dict,
        reform_policy: dict,
    ):
        logger.log(
            f"Starting CalculateEconomySimulationJob.run",
            context={
                "baseline_policy_id": baseline_policy_id,
                "policy_id": policy_id,
                "country_id": country_id,
                "region": region,
                "dataset": dataset,
                "time_period": time_period,
                "options": options,
            },
        )
        try:
            # Configure inputs
            # Note for anyone modifying options_hash: redis-queue treats ":" as a namespace
            # delimiter; don't use colons in options_hash
            options_hash = (
                "[" + "&".join([f"{k}={v}" for k, v in options.items()]) + "]"
            )
            baseline_policy_id = int(baseline_policy_id)
            policy_id = int(policy_id)

            # Check if a completed result already exists
            existing = reform_impacts_service.get_all_reform_impacts(
                country_id,
                policy_id,
                baseline_policy_id,
                region,
                dataset,
                time_period,
                options_hash,
                COUNTRY_PACKAGE_VERSIONS[country_id],
            )
            if any(x["status"] == "ok" for x in existing):
                logger.log(f"Job already completed successfully")
                return

            # Save identifiers for later commenting on processing status
            identifiers = (
                country_id,
                policy_id,
                baseline_policy_id,
                region,
                dataset,
                time_period,
                options_hash,
            )

            logger.log("Checking existing reform impacts...")
            # Query existing impacts before deleting
            existing = reform_impacts_service.get_all_reform_impacts(
                country_id,
                policy_id,
                baseline_policy_id,
                region,
                dataset,
                time_period,
                options_hash,
                COUNTRY_PACKAGE_VERSIONS[country_id],
            )
            logger.log(f"Found {len(existing)} existing impacts before delete")

            # Delete any existing reform impact rows with the same identifiers
            reform_impacts_service.delete_reform_impact(
                country_id,
                policy_id,
                baseline_policy_id,
                region,
                dataset,
                time_period,
                options_hash,
            )

            logger.log("Deleted existing computing impacts")

            # Insert new reform impact row with status 'computing'
            reform_impacts_service.set_reform_impact(
                country_id=country_id,
                policy_id=policy_id,
                baseline_policy_id=baseline_policy_id,
                region=region,
                dataset=dataset,
                time_period=time_period,
                options=json.dumps(options),
                options_hash=options_hash,
                status="computing",
                api_version=COUNTRY_PACKAGE_VERSIONS[country_id],
                reform_impact_json=json.dumps({}),
                start_time=datetime.datetime.strftime(
                    datetime.datetime.now(datetime.timezone.utc),
                    "%Y-%m-%d %H:%M:%S.%f",
                ),
            )

            comment = lambda x: set_comment_on_job(x, *identifiers)
            comment("Computing baseline")
            logger.log(
                "Computing baseline",
                context={
                    "country_id": country_id,
                    "region": region,
                    "dataset": dataset,
                    "time_period": time_period,
                    "options": options,
                },
            )

            # Compute baseline economy
            baseline_economy = self._compute_economy(
                country_id=country_id,
                region=region,
                dataset=dataset,
                time_period=time_period,
                options=options,
                policy_json=baseline_policy,
            )
            comment("Computing reform")
            logger.log(
                "Computing reform",
                context={
                    "country_id": country_id,
                    "region": region,
                    "dataset": dataset,
                    "time_period": time_period,
                    "options": options,
                },
            )

            # Compute reform economy
            reform_economy = self._compute_economy(
                country_id=country_id,
                region=region,
                dataset=dataset,
                time_period=time_period,
                options=options,
                policy_json=reform_policy,
            )

            baseline_economy = baseline_economy["result"]
            reform_economy = reform_economy["result"]
            comment("Comparing baseline and reform")
            logger.log(
                "Comparing baseline and reform",
                context={
                    "country_id": country_id,
                    "region": region,
                    "dataset": dataset,
                    "time_period": time_period,
                    "options": options,
                },
            )
            impact = compare_economic_outputs(
                baseline_economy, reform_economy, country_id=country_id
            )

            # Finally, update all reform impact rows with the same baseline and reform policy IDs
            reform_impacts_service.set_complete_reform_impact(
                country_id=country_id,
                reform_policy_id=policy_id,
                baseline_policy_id=baseline_policy_id,
                region=region,
                dataset=dataset,
                time_period=time_period,
                options_hash=options_hash,
                reform_impact_json=json.dumps(impact),
            )

        except Exception as e:
            reform_impacts_service.set_error_reform_impact(
                country_id,
                policy_id,
                baseline_policy_id,
                region,
                dataset,
                time_period,
                options_hash,
                message=traceback.format_exc(),
            )
            logger.error(
                f"Error setting reform impact",
                context={
                    "country_id": country_id,
                    "region": region,
                    "dataset": dataset,
                    "time_period": time_period,
                    "options": options,
                    "error": str(e),
                },
            )
            raise e

    def _compute_economy(
        self, country_id, region, dataset, time_period, options, policy_json
    ):
        try:

            # Begin measuring calculation length
            start = time.time()

            # Load country and policy data
            policy_data = json.loads(policy_json)

            # Create policy reform
            reform = create_policy_reform(policy_data)

            # Country-specific simulation configuration
            country = COUNTRIES.get(country_id)
            if country_id == "uk":
                simulation = self._create_simulation_uk(
                    country, reform, region, time_period
                )
            elif country_id == "us":
                simulation = self._create_simulation_us(
                    country, reform, region, dataset, time_period
                )

            # Subsample simulation
            simulation.subsample(
                int(
                    options.get(
                        "max_households",
                        os.environ.get("MAX_HOUSEHOLDS", 1_000_000),
                    )
                ),
                seed=(region, time_period),
                time_period=time_period,
            )
            simulation.default_calculation_period = time_period

            for time_period in simulation.get_holder(
                "person_weight"
            ).get_known_periods():
                simulation.delete_arrays("person_weight", time_period)

            if options.get("target") == "cliff":
                logger.log(f"Initialised cliff impact computation")
                return {
                    "status": "ok",
                    "result": self._compute_cliff_impacts(simulation),
                }
            print(f"Initialised simulation in {time.time() - start} seconds")
            start = time.time()
            economy = compute_general_economy(
                simulation,
                country_id=country_id,
            )
            print(f"Computed economy in {time.time() - start} seconds")
            return {"status": "ok", "result": economy}

        except Exception as e:
            print(f"Error computing economy: {str(e)}")
            raise e

    def _create_simulation_uk(
        self, country, reform, region, time_period
    ) -> Microsimulation:
        Microsimulation: type = country.country_package.Microsimulation

        simulation = Microsimulation(
            reform=reform,
        )
        simulation.default_calculation_period = time_period
        if region != "uk":
            region_values = simulation.calculate("country").values
            region_decoded = dict(
                eng="ENGLAND",
                wales="WALES",
                scot="SCOTLAND",
                ni="NORTHERN_IRELAND",
            )[region]
            df = simulation.to_input_dataframe()
            simulation = Microsimulation(
                dataset=df[region_values == region_decoded],
                reform=reform,
            )

        return simulation

    def _create_simulation_us(
        self, country, reform, region, dataset, time_period
    ) -> Microsimulation:
        Microsimulation: type = country.country_package.Microsimulation

        # Initialize settings
        sim_options = dict(
            reform=reform,
        )

        # Handle dataset settings
        # Permitted dataset settings
        DATASETS = ["enhanced_cps"]

        # Second statement provides backwards compatibility option
        # for running a simulation with the "enhanced_us" region
        if dataset in DATASETS or region == "enhanced_us":
            logger.log(f"Running an enhanced CPS simulation")
            from policyengine_us_data import EnhancedCPS_2024

            sim_options["dataset"] = EnhancedCPS_2024

        # Handle region settings; need to be mindful not to place
        # legacy enhanced_us region in this block
        if region not in ["us", "enhanced_us"]:
            logger.log(f"Filtering US dataset down to region {region}")

            from policyengine_us_data import Pooled_3_Year_CPS_2023

            # This is only run to allow for filtering by region
            # Check to see if we've declared a dataset and use that
            # to filter down by region
            if "dataset" in sim_options:
                filter_dataset = sim_options["dataset"]
            else:
                filter_dataset = Pooled_3_Year_CPS_2023

            # Run sim to filter by region
            region_sim = Microsimulation(
                dataset=filter_dataset,
                reform=reform,
            )
            df = region_sim.to_input_dataframe()
            state_code = region_sim.calculate(
                "state_code_str", map_to="person"
            ).values
            region_sim.default_calculation_period = time_period

            if region == "nyc":
                in_nyc = region_sim.calculate("in_nyc", map_to="person").values
                sim_options["dataset"] = df[in_nyc]

            else:
                sim_options["dataset"] = df[state_code == region.upper()]

        # Return completed simulation
        return Microsimulation(**sim_options)

    def _compute_cliff_impacts(self, simulation: Microsimulation) -> Dict:
        cliff_gap = simulation.calculate("cliff_gap")
        is_on_cliff = simulation.calculate("is_on_cliff")
        total_cliff_gap = cliff_gap.sum()
        total_adults = simulation.calculate("is_adult").sum()
        cliff_share = is_on_cliff.sum() / total_adults
        return {
            "cliff_gap": float(total_cliff_gap),
            "cliff_share": float(cliff_share),
            "type": "cliff",
        }
