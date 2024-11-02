from redis import Redis
from rq import Worker
from datetime import datetime

# Preload libraries
import policyengine_uk
import policyengine_us
import policyengine_canada
import policyengine_ng
from policyengine_api.endpoints.economy.reform_impact import (
    set_reform_impact_data,
)

# Logger will append `worker_` to front for filename, hence we'll
# define name as just the date and time
worker_id = datetime.now().strftime("%Y%m%d_%H%M%S")

# Provide the worker with the list of queues (str) to listen to.
w = Worker(["default"], connection=Redis(), name=worker_id)
w.work()
