"""Native FastAPI route for the v2 countries list."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse

from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.fastapi_routes.dependencies import (
    _default_v2_country_service_factory,
)
from policyengine_api.fastapi_routes.query_parameters import query_dependency
from policyengine_api.fastapi_routes.v2.countries.response_models import (
    COUNTRY_ERROR_RESPONSES,
    CountryItem,
    CountryListResponse,
    CountryListResult,
)
from policyengine_api.fastapi_routes.v2.errors import V2ErrorMapping, run_v2_operation
from policyengine_api.query_parameters import CountryListQuery

if TYPE_CHECKING:
    from collections.abc import Callable

    from policyengine_api.fastapi_routes.dependencies import (
        NativeRouteDependencies,
        V2CountryResourceService,
    )


CountryListQueryDependency = Annotated[
    CountryListQuery, Depends(query_dependency(CountryListQuery))
]

COUNTRY_ERROR_MAPPINGS = (
    V2ErrorMapping(
        (V2ConfigurationError, SQLAlchemyError),
        503,
        "V2 countries are unavailable",
    ),
)


def _service_factory(
    dependencies: NativeRouteDependencies,
) -> Callable[[], V2CountryResourceService]:
    if dependencies.v2_country_service_factory is not None:
        return dependencies.v2_country_service_factory
    return _default_v2_country_service_factory


def build_v2_country_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    """Build the countries route without opening a database connection."""
    router = APIRouter(prefix="/v2", responses=COUNTRY_ERROR_RESPONSES)
    service_factory = _service_factory(dependencies)

    @router.get(
        "/countries",
        response_model=CountryListResponse,
        summary="List the served countries and the calculations each supports",
    )
    def list_countries(
        _query: CountryListQueryDependency,
    ) -> CountryListResponse | JSONResponse:
        def read() -> CountryListResponse:
            countries = service_factory().list_countries()
            return CountryListResponse(
                result=CountryListResult(
                    items=[CountryItem.from_read(country) for country in countries]
                )
            )

        return run_v2_operation(
            read,
            COUNTRY_ERROR_MAPPINGS,
            fallback_message="V2 countries query failed",
        )

    return router
