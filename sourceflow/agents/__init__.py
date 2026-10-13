"""Samagra's agents. Importing the package registers every agent, so
`agents.all_agents()` is the list the Agents page shows and
`agents.get("offer")` is how a route or a hook fires one.

See base.py for what an agent is here - and, as importantly, what it is not.
"""

from .base import REGISTRY, Agent, RunLog, all_agents, get  # noqa: F401
from . import offer, enquiry, advisor  # noqa: F401,E402  - register on import
