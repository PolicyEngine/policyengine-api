"""Shared loader for the legacy public OpenAPI specification."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import yaml
from policyengine_api.constants import VERSION
from policyengine_api.fastapi_routes.types import JSONObject


DEFAULT_SPECIFICATION_PATH = Path(__file__).with_name("openapi_spec.yaml")


def load_specification(
    path: Path = DEFAULT_SPECIFICATION_PATH,
    version: str = VERSION,
) -> JSONObject:
    """Load the static specification and set the deployed package version."""
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("info"), dict):
        raise ValueError("OpenAPI specification must contain an info object")
    document["info"]["version"] = version
    return cast(JSONObject, document)


OPENAPI_SPECIFICATION = load_specification()
