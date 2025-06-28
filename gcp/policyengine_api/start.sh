#!/bin/sh
# Environment variables
PORT="${PORT:-8080}"

# Start the API
gunicorn -b :"$PORT" policyengine_api.api --timeout 300 --workers 5 &

# Keep the script running and handle shutdown gracefully
trap "pkill -P $$; exit 1" INT TERM

wait