"""Strict HTTP request models for v2 simulations."""

from policyengine_api.services.v2.simulation_service.types import (
    EconomySimulationCreationInput,
)


class SimulationCreateRequest(EconomySimulationCreationInput):
    """An economy simulation to create; ``country_id`` must match the query's.

    No field names a PolicyEngine.py version: the simulation service runs its
    default worker's.
    """
