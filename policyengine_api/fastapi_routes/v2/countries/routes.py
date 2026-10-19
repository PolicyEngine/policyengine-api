"""Native FastAPI route for the v2 countries list."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse

from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.fastapi_routes.query_parameters import query_dependency
from policyengine_api.fastapi_routes.v2.countries.response_models import (
    COUNTRY_ERROR_RESPONSES,
    CountryItem,
    CountryListResponse,
    CountryListResult,
)
from policyengine_api.fastapi_routes.v2.errors import v2_error_response
from policyengine_api.query_parameters import CountryListQuery

if TYPE_CHECKING:
    from collections.abc import Callable

    from policyengine_api.fastapi_routes.dependencies import (
        NativeRouteDependencies,
        V2CountryResourceService,
    )


def _service_factory(
    dependencies: NativeRouteDependencies,
) -> Callable[[], V2CountryResourceService]:
    if dependencies.v2_country_service_factory is not None:
        return dependencies.v2_country_service_factory
    from policyengine_api.fastapi_routes.dependencies import (
        _default_v2_country_service_factory,
    )

    return _default_v2_country_service_factory


def build_v2_country_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    """Build the countries route without opening a database connection."""
    router = APIRouter(prefix="/v2", responses=COUNTRY_ERROR_RESPONSES)
    list_query = query_dependency(CountryListQuery)
    service_factory = _service_factory(dependencies)

    @router.get(
        "/countries",
        response_model=CountryListResponse,
        summary="List countries and the calculations each supports",
    )
    def list_countries(
        _query: CountryListQuery = Depends(list_query),
    ) -> CountryListResponse | JSONResponse:
        try:
            countries = service_factory().list_countries()
        except (V2ConfigurationError, SQLAlchemyError):
            return v2_error_response(503, "V2 countries are unavailable")
        except Exception:  # noqa: BLE001  # route must return a secret-safe typed error
            return v2_error_response(500, "V2 countries query failed")
        return CountryListResponse(
            result=CountryListResult(
                items=[CountryItem.from_read(country) for country in countries]
            )
        )

    return router
