"""Strict requests for the internal Stage 12 persistence boundary."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from policyengine_api.services.v2.simulations.types import ContractText


class StrictStage12PersistenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class SimulationInvocationRequest(StrictStage12PersistenceRequest):
    expected_placeholder: ContractText
    modal_invocation_id: ContractText
    updated_at: datetime
