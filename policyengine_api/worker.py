from redis import Redis
from rq import Worker

# Preload libraries
import policyengine_uk
import policyengine_us
import policyengine_canada
import policyengine_ng
from policyengine_api.endpoints.economy.reform_impact import (
    set_reform_impact_data,
)

# Provide the worker with the list of queues (str) to listen to.
w = Worker(["default"], connection=Redis())
w.work()
