"""FastAPI dependency adapter for canonical query-parameter models."""

from __future__ import annotations

from collections.abc import Callable
from inspect import Parameter, Signature
from typing import Annotated, TypeVar

from fastapi import Query, Request
from fastapi.exceptions import RequestValidationError

from policyengine_api.query_parameters import (
    DuplicateScalarQueryParameterError,
    StrictQueryParameters,
    validate_scalar_query_multiplicity,
)


QueryParametersT = TypeVar("QueryParametersT", bound=StrictQueryParameters)


def _duplicate_error(error: DuplicateScalarQueryParameterError) -> dict[str, object]:
    return {
        "type": "value_error",
        "loc": ("query", error.parameter_name),
        "msg": "Input should occur only once for a scalar query parameter",
        "input": None,
        "ctx": {"error": error},
    }


def query_dependency(
    model_type: type[QueryParametersT],
) -> Callable[..., QueryParametersT]:
    """Build a typed dependency with runtime and OpenAPI query metadata."""

    async def dependency(
        request: Request,
        query: QueryParametersT,
    ) -> QueryParametersT:
        try:
            validate_scalar_query_multiplicity(
                model_type,
                request.query_params.multi_items(),
            )
        except DuplicateScalarQueryParameterError as error:
            raise RequestValidationError([_duplicate_error(error)]) from error
        return query

    dependency.__name__ = f"parse_{model_type.__name__}"
    dependency.__signature__ = Signature(  # type: ignore[attr-defined]
        parameters=(
            Parameter(
                "request",
                kind=Parameter.POSITIONAL_OR_KEYWORD,
                annotation=Request,
            ),
            Parameter(
                "query",
                kind=Parameter.POSITIONAL_OR_KEYWORD,
                annotation=Annotated[model_type, Query()],
            ),
        ),
        return_annotation=model_type,
    )
    return dependency
