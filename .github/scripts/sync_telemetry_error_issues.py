"""Report each day's telemetry error groups as GitHub issues.

The code is in the ``telemetry_error_issues`` package beside this file. Python
puts the directory of a script it runs by path first on ``sys.path``, so the
package imports from any working directory.
"""

from telemetry_error_issues.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
