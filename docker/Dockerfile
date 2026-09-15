FROM python:3.12
# Match the API bundle in pyproject.toml; the bundle updater changes both pins.
# Exact bundled model requirements prevent pip from silently backtracking.
RUN pip install "policyengine[models]==6.0.0" spm-calculator==1.0.0 ipython
