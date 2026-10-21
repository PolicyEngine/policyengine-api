#!/usr/bin/env bash
set -euo pipefail
coverage run -m pytest tests
python -m unittest discover -s tests
