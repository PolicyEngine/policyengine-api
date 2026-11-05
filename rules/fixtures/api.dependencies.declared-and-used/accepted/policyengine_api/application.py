"""Proof fixture for api.dependencies.declared-and-used (the accepted case).

pyproject.toml beside this package declares flask and starlette, the two
distributions this module imports.
"""

import flask
import starlette

IMPORTED_MODULES = (flask, starlette)
