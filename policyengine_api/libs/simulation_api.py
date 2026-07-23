"""Generic Simulation API client exports.

The implementation remains in ``simulation_api_modal`` temporarily so existing
imports and test patches keep working during the Stage 5 cutover.
"""

from policyengine_api.libs.simulation_api_modal import (
    ModalBudgetWindowBatchExecution,
    ModalSimulationExecution,
    SimulationAPIClient,
    SimulationAPIModal,
    resolve_simulation_api_url,
    simulation_api,
    simulation_api_modal,
)

__all__ = [
    "ModalBudgetWindowBatchExecution",
    "ModalSimulationExecution",
    "SimulationAPIClient",
    "SimulationAPIModal",
    "resolve_simulation_api_url",
    "simulation_api",
    "simulation_api_modal",
]
