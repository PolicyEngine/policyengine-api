from typing import Dict, Annotated
import json
import traceback
import datetime
import time
import os
import math
from typing import Type, Any, Literal
import pandas as pd
import numpy as np
from dotenv import load_dotenv
from google.cloud import workflows_v1
from google.cloud.workflows import executions_v1
from policyengine_api.gcp_logging import logger
from policyengine_api.jobs import BaseJob
from policyengine_api.jobs.tasks import compute_general_economy
from policyengine_api.services.reform_impacts_service import (
    ReformImpactsService,
)
from policyengine_api.endpoints.economy.compare import compare_economic_outputs
from policyengine_api.endpoints.economy.reform_impact import set_comment_on_job
from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.country import COUNTRIES, create_policy_reform
from policyengine_api.utils.v2_v1_comparison import (
    V2V1Comparison,
    compute_difference,
)
from policyengine_core.simulations import Microsimulation
from policyengine_core.tools.hugging_face import (
    download_huggingface_dataset,
    get_latest_commit_tag,
)
import h5py

from policyengine_us import Microsimulation
from policyengine_uk import Microsimulation
import logging
import huggingface_hub

load_dotenv()

reform_impacts_service = ReformImpactsService()

ENHANCED_FRS = "hf://policyengine/policyengine-uk-data/enhanced_frs_2022_23.h5"
FRS = "hf://policyengine/policyengine-uk-data/frs_2022_23.h5"

ENHANCED_CPS = "hf://policyengine/policyengine-us-data/enhanced_cps_2024.h5"
CPS = "hf://policyengine/policyengine-us-data/cps_2023.h5"
POOLED_CPS = "hf://policyengine/policyengine-us-data/pooled_3_year_cps_2023.h5"

datasets = {
    "uk": {
        "enhanced_frs": ENHANCED_FRS,
        "frs": FRS,
    },
    "us": {
        "enhanced_cps": ENHANCED_CPS,
        "cps": CPS,
        "pooled_cps": POOLED_CPS,
    },
}

uk_dataset_version = get_latest_commit_tag(
    repo_id="policyengine/policyengine-us-data",
    repo_type="model",
)
us_dataset_version = get_latest_commit_tag(
    repo_id="policyengine/policyengine-uk-data",
    repo_type="model",
)

for dataset in datasets["uk"]:
    datasets["uk"][dataset] = f"{datasets['uk'][dataset]}@{uk_dataset_version}"

for dataset in datasets["us"]:
    datasets["us"][dataset] = f"{datasets['us'][dataset]}@{us_dataset_version}"


check_against_api_v2 = (
    os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") is not None
)

if not check_against_api_v2:
    logging.warn(
        "Didn't find any GOOGLE_APPLICATION_CREDENTIALS, so will not check APIv1 results against APIv2."
    )


class CalculateEconomySimulationJob(BaseJob):
    def __init__(self):
        super().__init__()
        if check_against_api_v2:
            self.api_v2 = SimulationAPIv2()

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
        reform_policy: Annotated[str, "String-formatted JSON"],
    ):
        print(f"Starting CalculateEconomySimulationJob.run")
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
                print(f"Job already completed successfully")
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

            print("Checking existing reform impacts...")
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
            print(f"Found {len(existing)} existing impacts before delete")

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

            print("Deleted existing computing impacts")

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

            # If comparing against API v2, start job
            if check_against_api_v2:

                # Populate v2/v1 comparison config data; we will pass this
                # to GCP logs either on error or success
                comparison_data = {
                    "country_id": country_id,
                    "region": region,
                    "reform_policy": reform_policy,
                    "baseline_policy": baseline_policy,
                    "reform_policy_id": policy_id,
                    "baseline_policy_id": baseline_policy_id,
                    "time_period": time_period,
                    "dataset": dataset,
                    "v1_country_package_version": COUNTRY_PACKAGE_VERSIONS[
                        country_id
                    ],
                    "v2_id": None,  # Unavailable until job starts
                    "v2_country_package_version": None,  # Unavailable until job completes
                }

                # Set up APIv2 job
                comment("Setting up APIv2 job")
                sim_config: dict[str, Any] = self.api_v2._setup_sim_options(
                    country_id=country_id,
                    scope="macro",
                    reform_policy=reform_policy,
                    baseline_policy=baseline_policy,
                    time_period=time_period,
                    region=region,
                    dataset=dataset,
                    model_version=COUNTRY_PACKAGE_VERSIONS[country_id],
                    data_version=(
                        uk_dataset_version
                        if country_id == "uk"
                        else us_dataset_version
                    ),
                )

                try:
                    api_v2_execution = self.api_v2.run(sim_config)
                    execution_id = self.api_v2.get_execution_id(
                        api_v2_execution
                    )

                    comparison_data["v2_id"] = execution_id

                    # Pass name and status to logs
                    progress_log: V2V1Comparison = (
                        V2V1Comparison.model_validate(
                            {
                                **comparison_data,
                                "v1_impact": None,
                                "v2_impact": None,
                                "v1_v2_diff": None,
                                "message": "CALCULATE_ECONOMY_SIMULATION_JOB: APIv2 job started",
                            }
                        )
                    )
                    logger.log_struct(
                        progress_log.model_dump(mode="json"), severity="INFO"
                    )
                except Exception as e:
                    # Send error log to GCP
                    error_log: V2V1Comparison = V2V1Comparison.model_validate(
                        {
                            **comparison_data,
                            "v2_error": str(e),
                        }
                    )
                    logger.log_struct(
                        error_log.model_dump(mode="json"), severity="ERROR"
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
            impact: dict[str, Any] = compare_economic_outputs(
                baseline_economy, reform_economy, country_id=country_id
            )

            # If comparing against API v2, wait for job to complete
            if check_against_api_v2:

                try:
                    execution_id: str = self.api_v2.get_execution_id(
                        api_v2_execution
                    )
                    api_v2_output = self.api_v2.wait_for_completion(
                        api_v2_execution
                    )

                    v2_country_package_version = api_v2_output[
                        "country_package_version"
                    ]

                    completion_log: V2V1Comparison = (
                        V2V1Comparison.model_validate(
                            {
                                **comparison_data,
                                "v1_impact": impact,
                                "v2_impact": api_v2_output,
                                "v1_v2_diff": None,
                                "v2_country_package_version": v2_country_package_version,
                                "message": "CALCULATE_ECONOMY_SIMULATION_JOB: APIv2 job completed",
                            }
                        )
                    )

                    logger.log_struct(
                        completion_log.model_dump(mode="json"),
                    )
                    # Run v2/v1 comparison

                    v1_v2_diff: dict[str, Any] = compute_difference(
                        x=impact,
                        y=api_v2_output,
                    )
                    # Push relevant info into logging schema
                    comparison_log: V2V1Comparison = (
                        V2V1Comparison.model_validate(
                            {
                                **comparison_data,
                                "v1_impact": impact,
                                "v2_impact": api_v2_output,
                                "v1_v2_diff": v1_v2_diff,
                                "v2_country_package_version": v2_country_package_version,
                                "message": "CALCULATE_ECONOMY_SIMULATION_JOB: APIv2 job comparison with APIv1 completed",
                            }
                        )
                    )
                    logger.log_struct(
                        comparison_log.model_dump(mode="json"),
                        severity="INFO",
                    )

                except Exception as e:
                    # If job fails, send error log to GCP
                    error_log: V2V1Comparison = V2V1Comparison.model_validate(
                        {
                            **comparison_data,
                            "v2_error": str(e),
                            "v1_impact": impact,
                            "v2_impact": None,
                            "v1_v2_diff": None,
                            "message": "CALCULATE_ECONOMY_SIMULATION_JOB: APIv2 job failed",
                        }
                    )
                    logger.log_struct(
                        error_log.model_dump(mode="json"), severity="ERROR"
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
            if check_against_api_v2:
                # Show that API v1 failed and API v2 was not run
                error_log: V2V1Comparison = V2V1Comparison.model_validate(
                    {
                        "country_id": country_id,
                        "region": region,
                        "reform_policy": reform_policy,
                        "baseline_policy": baseline_policy,
                        "reform_policy_id": policy_id,
                        "baseline_policy_id": baseline_policy_id,
                        "time_period": time_period,
                        "dataset": dataset,
                        "v1_country_package_version": COUNTRY_PACKAGE_VERSIONS[
                            country_id
                        ],
                        "v2_id": None,  # Unavailable until job starts
                        "v2_country_package_version": None,  # Unavailable until job completes
                        "v1_error": str(e),
                        "v2_error": None,
                        "v1_impact": None,
                        "v2_impact": None,
                        "v1_v2_diff": None,
                        "message": "CALCULATE_ECONOMY_SIMULATION_JOB: APIv1 job failed",
                    }
                )
                logger.log_struct(
                    error_log.model_dump(mode="json"), severity="ERROR"
                )
            print(f"Error setting reform impact: {str(e)}")
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
            if (
                options.get("max_households", os.environ.get("MAX_HOUSEHOLDS"))
                is not None
            ):
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
                print(f"Initialised cliff impact computation")
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
        CountryMicrosimulation: Type[Microsimulation] = (
            country.country_package.Microsimulation
        )

        simulation = CountryMicrosimulation(
            reform=reform,
            dataset=datasets["uk"]["enhanced_frs"],
        )
        simulation.default_calculation_period = time_period
        if region != "uk":
            constituency_weights_path = download_huggingface_dataset(
                repo="policyengine/policyengine-uk-data-public",
                repo_filename="parliamentary_constituency_weights.h5",
            )
            constituency_names_path = download_huggingface_dataset(
                repo="policyengine/policyengine-uk-data-public",
                repo_filename="constituencies_2024.csv",
            )
            constituency_names = pd.read_csv(constituency_names_path)
            with h5py.File(constituency_weights_path, "r") as f:
                weights = f["2025"][...]
            if "constituency/" in region:
                constituency = region.split("/")[1]
                if constituency in constituency_names.code.values:
                    constituency_id = constituency_names[
                        constituency_names.code == constituency
                    ].index[0]
                elif constituency in constituency_names.name.values:
                    constituency_id = constituency_names[
                        constituency_names.name == constituency
                    ].index[0]
                else:
                    raise ValueError(
                        f"Constituency {constituency} not found. See {constituency_names_path} for the list of available constituencies."
                    )
                simulation.calculate("household_net_income", 2025)

                weights = weights[constituency_id]

                simulation.set_input("household_weight", 2025, weights)
                simulation.get_holder("person_weight").delete_arrays()
                simulation.get_holder("benunit_weight").delete_arrays()
            elif "country/" in region:
                self._apply_uk_country_filter(
                    region, weights, constituency_names, simulation
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

        if dataset in DATASETS:
            print(f"Running simulation using {dataset} dataset")

            sim_options["dataset"] = datasets["us"]["enhanced_cps"]

        # Handle region settings
        if region != "us":
            print(f"Filtering US dataset down to region {region}")

            # This is only run to allow for filtering by region
            # Check to see if we've declared a dataset and use that
            # to filter down by region
            if "dataset" in sim_options:
                filter_dataset = sim_options["dataset"]
            else:
                filter_dataset = datasets["us"]["pooled_cps"]

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

        if dataset == "default" and region == "us":
            sim_options["dataset"] = datasets["us"]["cps"]

        # Return completed simulation
        return Microsimulation(**sim_options)

    def _apply_uk_country_filter(
        self, region, weights, constituency_names, simulation
    ):
        """
        Apply a country filter for UK simulations based on constituency codes.

        Parameters:
        -----------
        region : str
            The region string in format 'country/{country}' where country can be
            england, scotland, wales, or ni.
        weights : np.array
            The constituency weights array from h5py file.
        constituency_names : pd.DataFrame
            Dataframe containing constituency codes and names.
        simulation : Microsimulation
            The microsimulation object to apply the filter to.
        """
        simulation.calculate("household_net_income", 2025)
        country_region = region.split("/")[1]

        # Map country region to prefix codes in constituency data
        country_region_code = {
            "england": "E",
            "scotland": "S",
            "wales": "W",
            "ni": "N",
        }[country_region]

        # Create a boolean mask for constituencies in the selected country
        weight_indices = constituency_names.code.str.startswith(
            country_region_code
        )

        # Apply the filter to the weights
        # weights shape = (650, 100180). weight_indices_shape = (650)
        weights_ = np.zeros((weights.shape[0], weights.shape[1]))
        weights_[weight_indices] = weights[weight_indices]
        weights_ = weights_.sum(axis=0)

        # Update the simulation with filtered weights
        simulation.set_input("household_weight", 2025, weights_)
        simulation.get_holder("person_weight").delete_arrays()
        simulation.get_holder("benunit_weight").delete_arrays()

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


class SimulationAPIv2:
    project: str
    location: str
    workflow: str

    def __init__(self):
        self.project = "prod-api-v2-c4d5"
        self.location = "us-central1"
        self.workflow = "simulation-workflow"

    def run(self, payload: dict) -> executions_v1.Execution:
        """
        Run a simulation using the v2 API

        Parameters:
        -----------
        payload : dict
            The payload to send to the API

        Returns:
        --------
        execution : executions_v1.Execution
            The execution object
        """
        self.execution_client = executions_v1.ExecutionsClient()
        self.workflows_client = workflows_v1.WorkflowsClient()
        json_input = json.dumps(payload)
        workflow_path = self.workflows_client.workflow_path(
            self.project, self.location, self.workflow
        )
        execution = self.execution_client.create_execution(
            parent=workflow_path,
            execution=executions_v1.Execution(argument=json_input),
        )
        return execution

    def get_execution_id(self, execution: executions_v1.Execution) -> str:
        return execution.name

    def get_execution_status(self, execution: executions_v1.Execution) -> str:
        """
        Get the status of an execution

        Parameters:
        -----------
        execution : executions_v1.Execution
            The execution object

        Returns:
        --------
        status : str
            The status of the execution
        """
        return self.execution_client.get_execution(
            name=execution.name
        ).state.name

    def get_execution_result(
        self, execution: executions_v1.Execution
    ) -> dict | None:
        """
        Get the result of an execution

        Parameters:
        -----------
        execution : executions_v1.Execution
            The execution object

        Returns:
        --------
        result : str
            The result of the execution
        """
        result = self.execution_client.get_execution(
            name=execution.name
        ).result
        try:
            return json.loads(result)
        except:
            return None
        return result

    def wait_for_completion(
        self, execution: executions_v1.Execution
    ) -> dict | None:
        """
        Wait for an execution to complete

        Parameters:
        -----------
        execution : executions_v1.Execution
            The execution object

        Returns:
        --------
        result : str
            The result of the execution
        """
        while self.get_execution_status(execution) == "ACTIVE":
            time.sleep(5)
            print("Waiting for APIv2 job to complete...")

        return self.get_execution_result(execution)

    def _setup_sim_options(
        self,
        country_id: str,
        reform_policy: Annotated[str, "String-formatted JSON"],
        baseline_policy: Annotated[str, "String-formatted JSON"],
        region: str,
        dataset: str,
        time_period: str,
        scope: Literal["macro", "household"] = "macro",
        model_version: str | None = None,
        data_version: str | None = None,
    ) -> dict[str, Any]:
        """
        Set up the simulation options for the APIv2 job.
        """

        return {
            "country": country_id,
            "scope": scope,
            "reform": json.loads(reform_policy),
            "baseline": json.loads(baseline_policy),
            "time_period": time_period,
            "region": self._setup_region(country_id=country_id, region=region),
            "data": self._setup_data(
                dataset=dataset, country_id=country_id, region=region
            ),
            "model_version": model_version,
            "data_version": data_version,
        }

    def _setup_region(self, country_id: str, region: str) -> str:
        """
        Convert API v1 'region' option to API v2-compatible 'region' option.
        """

        # For US, states must be prefixed with 'state/'
        if country_id == "us" and region != "us":
            return "state/" + region

        return region

    def _setup_data(
        self, dataset: str, country_id: str, region: str
    ) -> str | None:
        """
        Take API v1 'data' string literals, which reference a dataset name,
        and convert to relevant GCP filepath. In future, this should be
        redone to use a more robust method of accessing datasets.
        """

        # Enhanced CPS runs must reference ECPS dataset in Google Cloud bucket
        if dataset == "enhanced_cps":
            return "gs://policyengine-us-data/enhanced_cps_2024.h5"

        # US state-level simulations must reference pooled CPS dataset
        if country_id == "us" and region != "us":
            return "gs://policyengine-us-data/pooled_3_year_cps_2023.h5"

        # All others receive no sim API 'data' arg
        return None
