"""Typed FastAPI dependencies for the shared v2 metadata query contracts.

Route modules import these aliases into their own globals, because FastAPI
resolves an endpoint's string annotations against its module only.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from policyengine_api.fastapi_routes.query_parameters import query_dependency
from policyengine_api.query_parameters import (
    CatalogPageQuery,
    CatalogParameterQuery,
    CatalogQuery,
    CatalogVersionQuery,
    ParameterChildrenQuery,
    ParameterCollectionQuery,
    ParameterValueCollectionQuery,
    RegionCollectionQuery,
    VariableCollectionQuery,
)

CatalogQueryDependency = Annotated[
    CatalogQuery, Depends(query_dependency(CatalogQuery))
]
CatalogVersionQueryDependency = Annotated[
    CatalogVersionQuery, Depends(query_dependency(CatalogVersionQuery))
]
CatalogPageQueryDependency = Annotated[
    CatalogPageQuery, Depends(query_dependency(CatalogPageQuery))
]
VariableCollectionQueryDependency = Annotated[
    VariableCollectionQuery, Depends(query_dependency(VariableCollectionQuery))
]
RegionCollectionQueryDependency = Annotated[
    RegionCollectionQuery, Depends(query_dependency(RegionCollectionQuery))
]
ParameterChildrenQueryDependency = Annotated[
    ParameterChildrenQuery, Depends(query_dependency(ParameterChildrenQuery))
]
ParameterCollectionQueryDependency = Annotated[
    ParameterCollectionQuery, Depends(query_dependency(ParameterCollectionQuery))
]
ParameterValueCollectionQueryDependency = Annotated[
    ParameterValueCollectionQuery,
    Depends(query_dependency(ParameterValueCollectionQuery)),
]
CatalogParameterQueryDependency = Annotated[
    CatalogParameterQuery, Depends(query_dependency(CatalogParameterQuery))
]
