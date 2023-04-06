from redis import Redis
from rq import Worker

# Preload libraries
from policyengine_api.api import *

# Provide the worker with the list of queues (str) to listen to.
w = Worker(['default'], connection=Redis())
w.work()