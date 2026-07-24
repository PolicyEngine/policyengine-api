"""Legacy import shim for the canonical Simulation Entrypoint client."""

from policyengine_api.libs.simulation_entrypoint import (
    ModalBudgetWindowBatchExecution,
    ModalSimulationExecution,
    SimulationAPIClient,
    SimulationEntrypointClient,
    SimulationAPIModal,
    resolve_simulation_api_url,
    resolve_simulation_entrypoint_url,
    simulation_api,
    simulation_api_modal,
    simulation_entrypoint,
)

__all__ = [
    "ModalBudgetWindowBatchExecution",
    "ModalSimulationExecution",
    "SimulationAPIClient",
    "SimulationEntrypointClient",
    "SimulationAPIModal",
    "resolve_simulation_api_url",
    "resolve_simulation_entrypoint_url",
    "simulation_api",
    "simulation_api_modal",
    "simulation_entrypoint",
]
