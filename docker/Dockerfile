FROM python:3.12
# Match the API bundle in pyproject.toml; the bundle updater changes both pins.
# The models extra pins the complete certified runtime package set.
RUN pip install "policyengine[models]==6.2.3" ipython
