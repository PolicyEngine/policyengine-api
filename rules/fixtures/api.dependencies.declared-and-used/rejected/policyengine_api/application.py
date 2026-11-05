"""Proof fixture for api.dependencies.declared-and-used (the rejected case).

pyproject.toml beside this package doesn't declare starlette, declares pytest
only in the dev extra, and declares no distribution that provides
module_that_is_not_installed, so deptry reports each import.
"""

import module_that_is_not_installed
import pytest
import starlette

IMPORTED_MODULES = (module_that_is_not_installed, pytest, starlette)
