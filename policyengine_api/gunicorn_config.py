"""gunicorn settings for the Cloud Run service, loaded by gcp/cloud_run/start.sh.

gunicorn reads every top-level name here that matches one of its settings, so
this module defines only settings. The command-line options in start.sh take
precedence over them.
"""

from policyengine_api.gunicorn_worker_exits import child_exit, on_starting

__all__ = ["child_exit", "on_starting"]
