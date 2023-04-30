# PolicyEngine API

To debug locally, run `make debug` (and `make debug-compute` for the microsimulation server). Then in separate terminals runs `redis-server` and `python policyengine_api/worker.py` for the long-running tasks. You'll need to make sure `redis` is installed.

## Development rules

1. Every endpoint should return a JSON object with at least a "status" and "message" field.