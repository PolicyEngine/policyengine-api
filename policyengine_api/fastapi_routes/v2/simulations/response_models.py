"""Strict HTTP response models for v2 simulations."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from policyengine_api.fastapi_routes.v2.errors_support import V2ErrorResponse
from policyengine_api.fastapi_routes.v2.reports.response_models import (
    PackageVersionsItem,
)
from policyengine_api.fastapi_routes.v2.simulation_resources_support import (
    error_response,
)

if TYPE_CHECKING:
    from policyengine_api.services.v2.stored_simulations.types import SimulationRead


class StrictSimulationAPIModel(BaseModel):
    """Strict response base that converts the service's dataclass reads."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)


class SimulationRunItem(StrictSimulationAPIModel):
    """One calculation of a simulation, for one year on one package version pair."""

    id: UUID
    year: int
    status: Literal["pending", "running", "succeeded", "failed"]
    country_package_version: str
    policyengine_version: str
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class SimulationItem(StrictSimulationAPIModel):
    """A simulation, its newest run and the versions the Public API runs now.

    A null ``policy_id`` or ``dynamic_id`` is current law. An economy
    simulation names its region and dataset, a household simulation its
    household. ``status`` is the newest run's, or ``not_run``; a newest run
    on other versions than ``current_versions`` is out of date.
    """

    id: UUID
    country_id: str
    kind: Literal["economy", "household"]
    policy_id: UUID | None
    dynamic_id: UUID | None
    household_id: UUID | None
    year: int | None
    region_code: str | None
    dataset_name: str | None
    created_at: datetime
    status: Literal["not_run", "pending", "running", "succeeded", "failed"]
    run: SimulationRunItem | None
    current_versions: PackageVersionsItem

    @classmethod
    def from_read(cls, read: SimulationRead) -> SimulationItem:
        """Build the item from the service's read."""
        return cls.model_validate(read)


class SimulationDetailResult(StrictSimulationAPIModel):
    """Result holding one simulation in ``item``."""

    item: SimulationItem


ResultT = TypeVar("ResultT")


class SimulationSuccessResponse(StrictSimulationAPIModel, Generic[ResultT]):
    """Success envelope: ``status`` "ok", a null ``message`` and the ``result``."""

    status: Literal["ok"] = "ok"
    message: None = None
    result: ResultT


class SimulationDetailResponse(SimulationSuccessResponse[SimulationDetailResult]):
    """Success response holding one simulation."""


class CreatedSimulationUnreadableResponse(V2ErrorResponse):
    """The 502 answer when the created simulation cannot be read back.

    The simulation service created ``simulation_id``, so the caller reads it
    with ``GET /v2/simulations/{simulation_id}`` rather than submitting it
    again.
    """

    simulation_id: UUID


class UnavailableAfterSimulationCreatedResponse(V2ErrorResponse):
    """The 503 answer when the simulation service failed a new simulation's run.

    The message gives the service's code and reason. ``simulation_id`` names
    the simulation, which ``GET /v2/simulations/{simulation_id}`` reads with
    its failed run.
    """

    simulation_id: UUID


SIMULATION_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    422: error_response("The request does not match the schema."),
    500: error_response("The operation could not be completed."),
    503: error_response("The v2 database or the simulation service is unavailable."),
}
READ_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: error_response("No simulation of this country's model has this ID."),
}
CREATE_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: error_response("The body and query name different countries."),
    404: error_response(
        "The policy the simulation names is not stored in the country."
    ),
    413: error_response("The request body exceeds 16 KiB."),
    422: error_response(
        "The request does not match the schema, the country has no economy "
        "calculations, or the simulation service cannot run the simulation: "
        "its 422, or its 400 for a region, dataset or dynamic it does not "
        "have. The message says which, with the service's code and reason."
    ),
    502: {
        "model": V2ErrorResponse | CreatedSimulationUnreadableResponse,
        "description": (
            "The simulation service may have created the simulation, but its "
            "answer does not say so: the answer was lost after the request may "
            "have reached it; a proxy in front of it answered 502 or 504 in its "
            "place; it answered 503 in a shape the Public API cannot read, or "
            "naming only another record; or it failed (500). The message says "
            "which, and asks the caller to submit the simulation again, which "
            "creates a second simulation if the first request went through. Or "
            "it created the simulation, but its answer cannot be read. Or it "
            "created the simulation, but the simulation cannot be read back: "
            "the answer gives its simulation_id, to read with GET "
            "/v2/simulations/{simulation_id} rather than submitting it again."
        ),
    },
    503: {
        "model": V2ErrorResponse | UnavailableAfterSimulationCreatedResponse,
        "description": (
            "The simulation service created nothing: it cannot be reached or is "
            "not configured; it answered a readable 503 naming no record, or a "
            "400 naming no region, dataset or dynamic of the caller's (such as "
            "a catalog version missing while a release deploys), and the "
            "message gives its code and reason; or it answered 400 or 422 in a "
            "shape the Public API cannot read, or another status. Or the v2 "
            "database is unavailable. Or the service created the simulation, "
            "then Modal refused the run's call and the service failed the run: "
            "its 503 named the simulation, and the answer gives its "
            "simulation_id."
        ),
    },
}
