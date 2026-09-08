#!/usr/bin/env python3
"""Apply the Stage 11 runtime privileges after the v2 schema upgrade."""

from policyengine_api.data.v2.runtime_privileges import main


if __name__ == "__main__":
    raise SystemExit(main())
