from pathlib import Path

import pytest


SERVICE_ROOT = Path(__file__).parents[3] / "policyengine_api" / "services"
DAO_MODULE = SERVICE_ROOT.parent / "data" / "v1_daos.py"


@pytest.mark.parametrize(
    "module_name",
    ["household_service.py", "policy_service.py", "user_service.py"],
)
def test_migrated_services_do_not_issue_queries_directly(module_name):
    source = (SERVICE_ROOT / module_name).read_text(encoding="utf-8")
    assert ".query(" not in source
    assert "from policyengine_api.data import database" not in source


@pytest.mark.parametrize(
    "module_name",
    ["household_service.py", "policy_service.py", "user_service.py"],
)
def test_migrated_services_use_sessions_and_mapped_models(module_name):
    source = (SERVICE_ROOT / module_name).read_text(encoding="utf-8")
    assert "from sqlalchemy.orm import Session" in source
    assert "from policyengine_api.data.v1_daos" not in source
    assert "build_v1_session_manager" not in source


def test_migrated_user_domains_have_no_temporary_daos():
    source = DAO_MODULE.read_text(encoding="utf-8")
    assert "class UserDAO" not in source
    assert "class UserPolicyDAO" not in source
    assert "class EconomyDAO" not in source
