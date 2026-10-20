#!/usr/bin/env python3
"""Grant or check the v2 table privileges the manifest declares.

Usage: ``reconcile_v2_privileges.py apply [--create-missing-roles]`` or
``reconcile_v2_privileges.py verify``. See
``policyengine_api.data.v2.privilege_reconciliation``.
"""

from policyengine_api.data.v2.privilege_reconciliation import main

if __name__ == "__main__":
    raise SystemExit(main())
