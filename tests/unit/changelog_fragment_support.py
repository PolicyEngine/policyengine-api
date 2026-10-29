"""Load .github/changelog_fragments.py and .github/bump_version.py for tests.

``python .github/bump_version.py`` puts .github/ first on ``sys.path``, so the
bump script imports ``changelog_fragments`` from the file beside it. These
helpers load both files by path and register each under its module name, so
the bump script's import finds the fragment module without a change to
``sys.path``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

REPO = Path(__file__).resolve().parents[2]
GITHUB_DIRECTORY = REPO / ".github"


def load_github_module(module_name: str) -> ModuleType:
    """Return the module in .github/<module_name>.py, loading it on first use."""
    loaded_module = sys.modules.get(module_name)
    if loaded_module is not None:
        return loaded_module
    spec = importlib.util.spec_from_file_location(
        module_name, GITHUB_DIRECTORY / f"{module_name}.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[module_name]
        raise
    return module


def changelog_fragments() -> ModuleType:
    """Return .github/changelog_fragments.py."""
    return load_github_module("changelog_fragments")


def bump_version() -> ModuleType:
    """Return .github/bump_version.py, after the fragment module it imports."""
    changelog_fragments()
    return load_github_module("bump_version")
