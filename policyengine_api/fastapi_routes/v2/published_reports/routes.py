"""Native FastAPI routes that publish saved reports, and read them publicly.

An author or admin publishes one of their saved reports as a public,
read-only page, which shows one succeeded run of its report, with a
summary, authors, tags and content of its own. The owner's routes take the
user-report routes' credentials: publishing, editing and moving the page to
a newer run need author or above (403 below it), and reading the owner's
page and withdrawing it need only ownership, so an author who was demoted
can still withdraw what they published. Anyone reads a published report by
its saved report's ID, with no credential.
"""

# No postponed annotations: FastAPI resolves each route's dependency
# annotations at runtime, and the author check is a dependency local to the
# router builder.
from collections.abc import Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from starlette.responses import JSONResponse, Response

from policyengine_api.data.v2.models import UserType
from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.fastapi_routes.dependencies import (
    NativeRouteDependencies,
    V2PublishedReportResourceService,
    V2UserTypeResourceService,
    _default_v2_published_report_service_factory,
    _default_v2_user_type_service_factory,
)
from policyengine_api.fastapi_routes.query_parameters import query_dependency
from policyengine_api.fastapi_routes.v2.errors_support import (
    V2ErrorMapping,
    V2ErrorResponse,
)
from policyengine_api.fastapi_routes.v2.published_reports.request_models import (
    PublicationCreateRequest,
    PublicationPatchRequest,
    PublicationVersionRequest,
)
from policyengine_api.fastapi_routes.v2.published_reports.response_models import (
    PublicationDetailResponse,
    PublicationDetailResult,
    PublicationItem,
    PublishedReportDetailResponse,
    PublishedReportDetailResult,
    PublishedReportItem,
)
from policyengine_api.fastapi_routes.v2.simulation_resources_support import (
    simulation_resource_operation,
)
from policyengine_api.fastapi_routes.v2.user_resources_support import (
    USER_RESOURCE_ERROR_RESPONSES,
    request_size_limit,
    user_resource_operation,
)
from policyengine_api.fastapi_routes.v2.user_type_support import (
    minimum_user_type_dependency,
)
from policyengine_api.query_parameters import CountryQuery, PublishedReportQuery
from policyengine_api.services.v2.identity.types import AccountPrincipal
from policyengine_api.services.v2.published_reports.types import (
    PublicationRead,
)
from policyengine_api.services.v2.published_reports.validators import (
    PublishedReportNotFoundError,
    PublishedReportStorageError,
    PublishedVersionNotFoundError,
)
from policyengine_api.services.v2.stored_reports.budget_window_results.types import (
    BudgetWindowResultUnreadableError,
)
from policyengine_api.services.v2.stored_reports.economy_results.types import (
    EconomyResultUnreadableError,
)
from policyengine_api.services.v2.stored_reports.household_results.types import (
    HouseholdResultUnreadableError,
)
from policyengine_api.services.v2.stored_reports.validators import (
    ReportStorageError,
)

# A page's content may hold 100 Markdown blocks of 20,000 characters each:
# up to 8 MB in UTF-8, or 12 MB as JSON that escapes every character outside
# ASCII (6 bytes each, outside supplementary planes), within this limit.
MAXIMUM_PUBLICATION_REQUEST_BYTES = 16 * 1024 * 1024
enforce_publication_request_size = request_size_limit(
    MAXIMUM_PUBLICATION_REQUEST_BYTES, label="16 MiB"
)

# Every owner route's failures; each write adds its own.
PUBLICATION_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: USER_RESOURCE_ERROR_RESPONSES[401],
    403: {
        "model": V2ErrorResponse,
        "description": "Machine (client-credentials) principals are not permitted.",
    },
    404: {
        "model": V2ErrorResponse,
        "description": (
            "The saved report does not exist, belongs to another user, or is "
            "not published."
        ),
    },
    422: {
        "model": V2ErrorResponse,
        "description": "The ID, the query or the body does not match the schema.",
    },
    500: USER_RESOURCE_ERROR_RESPONSES[500],
    503: USER_RESOURCE_ERROR_RESPONSES[503],
}
_AUTHOR_REQUIRED = {
    "model": V2ErrorResponse,
    "description": (
        "Publishing, editing and moving a published report need an author or "
        "admin; machine (client-credentials) principals are not permitted."
    ),
}
_BODY_TOO_LARGE = {
    "model": V2ErrorResponse,
    "description": "The request body exceeds 16 MiB.",
}
PUBLISH_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    403: _AUTHOR_REQUIRED,
    404: {
        "model": V2ErrorResponse,
        "description": (
            "The saved report does not exist or belongs to another user, or "
            "the run is not one of its report's runs."
        ),
    },
    409: {
        "model": V2ErrorResponse,
        "description": (
            "The saved report is published already, names only a v1 report "
            "output or has no name; or the run has not succeeded."
        ),
    },
    413: _BODY_TOO_LARGE,
}
EDIT_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    403: _AUTHOR_REQUIRED,
    404: {
        "model": V2ErrorResponse,
        "description": (
            "The saved report does not exist, belongs to another user, or is "
            "not published."
        ),
    },
    413: _BODY_TOO_LARGE,
}
MOVE_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    403: _AUTHOR_REQUIRED,
    404: {
        "model": V2ErrorResponse,
        "description": (
            "The saved report does not exist, belongs to another user or is "
            "not published, or the run is not one of its report's runs."
        ),
    },
    409: {
        "model": V2ErrorResponse,
        "description": "The run has not succeeded, or the page has shown it already.",
    },
    413: _BODY_TOO_LARGE,
}

PUBLISHED_REPORT_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {
        "model": V2ErrorResponse,
        "description": (
            "No published report has this ID in this country, or it has no "
            "version with version_id that readers may open."
        ),
    },
    422: {
        "model": V2ErrorResponse,
        "description": "The ID or the query does not match the schema.",
    },
    500: {
        "model": V2ErrorResponse,
        "description": "The report's stored result cannot be read.",
    },
    503: {
        "model": V2ErrorResponse,
        "description": "V2 report storage is unavailable.",
    },
}
PUBLISHED_REPORT_REFUSALS: tuple[type[Exception], ...] = (
    PublishedReportNotFoundError,
    PublishedVersionNotFoundError,
)
PUBLISHED_REPORT_ERROR_MAPPINGS = (
    V2ErrorMapping(PUBLISHED_REPORT_REFUSALS, 404),
    V2ErrorMapping(
        (
            EconomyResultUnreadableError,
            HouseholdResultUnreadableError,
            BudgetWindowResultUnreadableError,
        ),
        500,
        "The report's stored result cannot be read",
    ),
    V2ErrorMapping(
        (PublishedReportStorageError, ReportStorageError, V2ConfigurationError),
        503,
        "V2 report storage is unavailable",
    ),
)

CountryQueryDependency = Annotated[
    CountryQuery, Depends(query_dependency(CountryQuery))
]
PublishedReportQueryDependency = Annotated[
    PublishedReportQuery, Depends(query_dependency(PublishedReportQuery))
]


def _service_factory(
    dependencies: NativeRouteDependencies,
) -> Callable[[], V2PublishedReportResourceService]:
    if dependencies.v2_published_report_service_factory is not None:
        return dependencies.v2_published_report_service_factory
    return _default_v2_published_report_service_factory


def _user_type_service_factory(
    dependencies: NativeRouteDependencies,
) -> Callable[[], V2UserTypeResourceService]:
    if dependencies.v2_user_type_service_factory is not None:
        return dependencies.v2_user_type_service_factory
    return _default_v2_user_type_service_factory


def _publication_answer(
    operation: Callable[[], PublicationRead],
) -> PublicationDetailResponse | JSONResponse:
    """Run one owner operation and answer its published report, or its failure."""

    def answered() -> PublicationDetailResponse:
        return PublicationDetailResponse(
            result=PublicationDetailResult(item=PublicationItem.from_read(operation()))
        )

    return user_resource_operation(answered)


def build_v2_user_report_publication_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    """Build the owner's publication routes without opening a connection.

    Authentication is a router-level dependency, so a missing or invalid
    credential is refused before the author check, the query or the body.
    """
    require_user = dependencies.require_user
    require_author = minimum_user_type_dependency(
        require_user, _user_type_service_factory(dependencies), UserType.AUTHOR
    )
    router = APIRouter(
        prefix="/v2",
        responses=PUBLICATION_ERROR_RESPONSES,
        dependencies=[
            Depends(require_user),
            Depends(enforce_publication_request_size),
        ],
    )
    service_factory = _service_factory(dependencies)
    path = "/user-reports/{association_id}/publication"

    @router.post(
        path,
        response_model=PublicationDetailResponse,
        status_code=201,
        dependencies=[Depends(require_author)],
        responses=PUBLISH_ERROR_RESPONSES,
        summary="Publish one of the current user's saved reports",
        description=(
            "Authors and admins only (403 below author). Publishes the saved "
            "report as a public, read-only page, linked by the saved report's "
            "ID (GET /v2/published-reports/{id}), showing the run run_id of "
            "the detailed-save report it names: a report run of an economy or "
            "household report, or a budget window's budget-window run, which "
            "must have succeeded (409 otherwise; 404 for a run that isn't one "
            "of the report's). The page's summary (1 to 300 characters), "
            "author_ids (1 to 10 IDs from the website's authors.json) and tags "
            "(up to 20 of the website's topic and location tags) show on its "
            "card; content is an ordered list of at most 100 blocks, Markdown "
            "(at most 20,000 characters each, rendered without raw HTML) or "
            "an output card by v3's key, each card at most once; a card left "
            "out is removed. With show_past_versions, readers may open the "
            "page's earlier versions. A saved report is published once (409); "
            "one that names only a v1 report output, or has no name, the "
            "page's title, can't be (409). A published saved report can't be "
            "repointed to another report until it is withdrawn, and deleting "
            "it, or its owner's account, deletes the page."
        ),
    )
    def publish_report(
        association_id: UUID,
        body: PublicationCreateRequest,
        query: CountryQueryDependency,
        principal: Annotated[AccountPrincipal, Depends(require_user)],
    ) -> PublicationDetailResponse | JSONResponse:
        return _publication_answer(
            lambda: service_factory().publish_report(
                principal=principal,
                country_id=query.country_id,
                user_report_id=association_id,
                publication_input=body,
            )
        )

    @router.get(
        path,
        response_model=PublicationDetailResponse,
        summary="Read the current user's published report",
        description=(
            "Any owner, whatever their type. Returns the published report "
            "with every version, newest first: the newest is the one the page "
            "shows. 404 when the saved report isn't published."
        ),
    )
    def get_publication(
        association_id: UUID,
        query: CountryQueryDependency,
        principal: Annotated[AccountPrincipal, Depends(require_user)],
    ) -> PublicationDetailResponse | JSONResponse:
        return _publication_answer(
            lambda: service_factory().get_publication(
                principal=principal,
                country_id=query.country_id,
                user_report_id=association_id,
            )
        )

    @router.patch(
        path,
        response_model=PublicationDetailResponse,
        dependencies=[Depends(require_author)],
        responses=EDIT_ERROR_RESPONSES,
        summary="Edit the current user's published report",
        description=(
            "Authors and admins only (403 below author). Sets the fields "
            "sent, checked as on publishing; none may be null, and the others "
            "stay. The content is the whole page's, for every version."
        ),
    )
    def update_publication(
        association_id: UUID,
        body: PublicationPatchRequest,
        query: CountryQueryDependency,
        principal: Annotated[AccountPrincipal, Depends(require_user)],
    ) -> PublicationDetailResponse | JSONResponse:
        return _publication_answer(
            lambda: service_factory().update_publication(
                principal=principal,
                country_id=query.country_id,
                user_report_id=association_id,
                publication_input=body,
            )
        )

    @router.delete(
        path,
        response_model=None,
        status_code=204,
        response_class=Response,
        summary="Withdraw the current user's published report",
        description=(
            "Any owner, whatever their type, so an author who was demoted can "
            "still withdraw it. Deletes the published report with its "
            "versions; its public read answers 404 from then on. The saved "
            "report stays."
        ),
    )
    def withdraw_publication(
        association_id: UUID,
        query: CountryQueryDependency,
        principal: Annotated[AccountPrincipal, Depends(require_user)],
    ) -> Response | JSONResponse:
        def withdraw() -> Response:
            service_factory().withdraw_publication(
                principal=principal,
                country_id=query.country_id,
                user_report_id=association_id,
            )
            return Response(status_code=204)

        return user_resource_operation(withdraw)

    @router.post(
        f"{path}/versions",
        response_model=PublicationDetailResponse,
        status_code=201,
        dependencies=[Depends(require_author)],
        responses=MOVE_ERROR_RESPONSES,
        summary="Move the current user's published report to another run",
        description=(
            "Authors and admins only (403 below author). The page shows the "
            "run run_id of its report from now on, as its new version, which "
            "must have succeeded (409 otherwise; 404 for a run that isn't one "
            "of the report's) and which it hasn't shown before (409). Earlier "
            "versions stay, and readers may open them while show_past_versions "
            "is on. Running the report again never moves the page."
        ),
    )
    def add_publication_version(
        association_id: UUID,
        body: PublicationVersionRequest,
        query: CountryQueryDependency,
        principal: Annotated[AccountPrincipal, Depends(require_user)],
    ) -> PublicationDetailResponse | JSONResponse:
        return _publication_answer(
            lambda: service_factory().add_publication_version(
                principal=principal,
                country_id=query.country_id,
                user_report_id=association_id,
                version_input=body,
            )
        )

    return router


def build_v2_published_report_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    """Build the credential-free read of a published report."""
    router = APIRouter(prefix="/v2", responses=PUBLISHED_REPORT_ERROR_RESPONSES)
    service_factory = _service_factory(dependencies)

    @router.get(
        "/published-reports/{user_report_id}",
        response_model=PublishedReportDetailResponse,
        summary="Read a published report",
        description=(
            "Needs no credential and never provisions a user. Returns the "
            "published report by its saved report's ID: its title (the saved "
            "report's name), summary, author IDs, tags and content; the saved "
            "report's source note, provisions, validation, budget window and "
            "the name of the reform it was compared with; the version read "
            "and the versions a reader may open (every version while "
            "show_past_versions, else only the newest), each with its run's "
            "versions and when the page moved to it; and the report with that "
            "version's run, as GET /v2/reports/{id}?run_id= answers it, "
            "labelled with the title. Without version_id, the newest version "
            "is read; version_id names one a reader may open (404 otherwise). "
            "The owner, the owner's notes and the owner's saved-reform IDs "
            "are left out."
        ),
    )
    def get_published_report(
        user_report_id: UUID,
        query: PublishedReportQueryDependency,
    ) -> PublishedReportDetailResponse | JSONResponse:
        def read() -> PublishedReportDetailResponse:
            published = service_factory().get_published_report(
                country_id=query.country_id,
                user_report_id=user_report_id,
                version_id=query.version_id,
            )
            return PublishedReportDetailResponse(
                result=PublishedReportDetailResult(
                    item=PublishedReportItem.from_read(published)
                )
            )

        return simulation_resource_operation(
            read,
            PUBLISHED_REPORT_ERROR_MAPPINGS,
            refusals=PUBLISHED_REPORT_REFUSALS,
            event="v2_published_report_read_failed",
            fallback_message="V2 published report read failed",
        )

    return router
