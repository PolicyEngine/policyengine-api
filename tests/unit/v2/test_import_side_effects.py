"""Import/startup tests for dormant and fail-closed v2 configuration."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

from policyengine_api.data.v2.settings import (
    V2_RUNTIME_DATABASE_URL,
    V2_SUPABASE_ENVIRONMENT,
    V2_SUPABASE_PROJECT_REF,
    V2ConfigurationError,
    load_v2_runtime_database_settings,
)


V2_ENVIRONMENT_NAMES = (
    "V2_RUNTIME_DATABASE_URL",
    "V2_MIGRATION_DATABASE_URL",
    "V2_SUPABASE_PROJECT_REF",
    "V2_SUPABASE_ENVIRONMENT",
    "V2_SUPABASE_STORAGE_URL",
    "V2_SUPABASE_STORAGE_ADMIN_KEY",
    "V2_SUPABASE_STORAGE_BUCKET",
)


def _environment_without_v2() -> dict[str, str]:
    environment = os.environ.copy()
    for name in V2_ENVIRONMENT_NAMES:
        environment.pop(name, None)
    environment["POLICYENGINE_API_STARTUP_WARMUP"] = "0"
    environment.pop("FLASK_DEBUG", None)
    environment.pop("K_SERVICE", None)
    environment.pop("GAE_ENV", None)
    for name in (
        "RUNTIME_CACHE_MODE",
        "RUNTIME_CACHE_URL",
        "RUNTIME_CACHE_CA_CERT",
        "RUNTIME_CACHE_URL_SECRET_RESOURCE",
        "RUNTIME_CACHE_CA_CERT_SECRET_RESOURCE",
        "RUNTIME_CACHE_ENVIRONMENT",
        "RUNTIME_CACHE_SERVICE",
    ):
        environment.pop(name, None)
    return environment


def test_importing_v2_modules_opens_no_network_and_creates_no_files(
    tmp_path: Path,
) -> None:
    script = """
import pathlib
import socket

def reject_connect(*args, **kwargs):
    raise AssertionError("module import attempted a network connection")

socket.socket.connect = reject_connect
before = set(pathlib.Path.cwd().iterdir())
import policyengine_api.data.v2.settings
import policyengine_api.data.v2.database
from policyengine_api.data.v2.models import V2_METADATA
after = set(pathlib.Path.cwd().iterdir())
assert before == after
assert len(V2_METADATA.tables) == 32
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=_environment_without_v2(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []


def test_default_cloud_sql_startup_requires_no_supabase_configuration(
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import policyengine_api.asgi"],
        cwd=tmp_path,
        env=_environment_without_v2(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "policyengine.db").exists()
    assert not list(tmp_path.glob("*.init.lock"))


@pytest.mark.parametrize("debug", ["0", "1"])
def test_import_startup_and_request_never_create_runtime_sqlite(
    tmp_path: Path,
    debug: str,
) -> None:
    environment = _environment_without_v2()
    environment["FLASK_DEBUG"] = debug
    script = """
from pathlib import Path
from policyengine_api.api import app

response = app.test_client().get('/liveness-check')
assert response.status_code == 200
assert not Path('policyengine.db').exists()
assert not list(Path.cwd().glob('*.db'))
assert not list(Path.cwd().glob('*.init.lock'))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []


def test_runtime_sqlite_modules_are_absent_from_production_package() -> None:
    data_root = Path(__file__).parents[3] / "policyengine_api/data"
    assert not (data_root / "local_database.py").exists()
    assert not (data_root / "local_models.py").exists()


def test_selected_v2_runtime_without_its_url_fails_closed() -> None:
    with pytest.raises(V2ConfigurationError, match=V2_RUNTIME_DATABASE_URL):
        load_v2_runtime_database_settings(
            {
                V2_SUPABASE_PROJECT_REF: "abcdefghijklmnopqrst",
                V2_SUPABASE_ENVIRONMENT: "test-foundation",
                "ALEMBIC_DATABASE_URL": "mysql+pymysql://v1:secret@db/v1",
                "FLASK_DEBUG": "1",
            }
        )
