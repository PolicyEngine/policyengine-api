FROM python:3.12
# Match the API's certified bundle: core 3.30.1, US 1.764.6, UK 2.90.2.
# Exact bundled model requirements prevent pip from silently backtracking.
RUN pip install "policyengine[models]==5.2.0" spm-calculator==0.3.1 ipython
