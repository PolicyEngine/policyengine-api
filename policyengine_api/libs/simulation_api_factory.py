"""
Factory for selecting the appropriate Simulation API implementation.

This module provides a factory function that returns either the GCP Workflows-based
SimulationAPI or the Modal-based SimulationAPIModal, depending on environment
configuration.

Environment Variables
---------------------
USE_MODAL_SIMULATION_API : str
    Set to "true" to use the Modal simulation API. Defaults to "false" (GCP).
"""

import os
from typing import Union

from policyengine_api.gcp_logging import logger


def get_simulation_api() -> (
    Union["SimulationAPI", "SimulationAPIModal"]
):  # noqa: F821
    """
    Get the appropriate simulation API client based on environment configuration.

    Returns the Modal-based client if USE_MODAL_SIMULATION_API is set to "true",
    otherwise returns the GCP Workflows-based client.

    Returns
    -------
    SimulationAPI or SimulationAPIModal
        The simulation API client instance.

    Raises
    ------
    ValueError
        If GCP client is requested but GOOGLE_APPLICATION_CREDENTIALS is not set.
    """
    use_modal = (
        os.environ.get("USE_MODAL_SIMULATION_API", "true").lower() == "true"
    )

    if use_modal:
        logger.log_struct(
            {"message": "Using Modal simulation API"},
            severity="INFO",
        )
        from policyengine_api.libs.simulation_api_modal import (
            simulation_api_modal,
        )

        return simulation_api_modal
    else:
        logger.log_struct(
            {"message": "Using GCP Workflows simulation API"},
            severity="INFO",
        )
        from policyengine_api.libs.simulation_api import SimulationAPI

        return SimulationAPI()
