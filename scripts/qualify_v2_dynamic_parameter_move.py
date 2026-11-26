#!/usr/bin/env python3
"""Check that no policy value names a dynamic parameter before revision 7f7335f0eb31."""

from policyengine_api.data.v2.dynamic_parameter_move_qualification import main

if __name__ == "__main__":
    raise SystemExit(main())
