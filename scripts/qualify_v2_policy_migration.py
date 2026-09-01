#!/usr/bin/env python3
"""Verify that a Supabase target has no retained v2 policy data."""

from policyengine_api.data.v2.policy_migration_qualification import main


if __name__ == "__main__":
    raise SystemExit(main())
