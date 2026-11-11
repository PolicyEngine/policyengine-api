"""Strict HTTP response models for v2 simulations."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict

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
        "calculations, or the simulation service cannot run the simulation; "
        "the message says which."
    ),
    502: error_response(
        "The simulation service created the simulation, but its answer cannot "
        "be read; it failed (500); its answer was lost after the submission may "
        "have reached it; or a proxy in front of it answered 502 or 504 in its "
        "place. In each case it may have created the simulation, so submitting "
        "again could create another."
    ),
    503: error_response(
        "The simulation service is unavailable or cannot be reached, or "
        "refuses in a shape the Public API cannot read; or the v2 database is "
        "unavailable."
    ),
}
