"""Make the telemetry_error_issues package importable, as running the script does.

Python puts the directory of a script it runs by path first on ``sys.path``,
which is how ``sync_telemetry_error_issues.py`` imports the package beside it.
"""

import sys
from pathlib import Path

SCRIPTS_DIRECTORY = Path(__file__).resolve().parents[3] / ".github" / "scripts"

if str(SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIRECTORY))
