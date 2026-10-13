"""The one shape every Samagra agent has.

An agent here is not an LLM deciding which tool to call in a loop. It is a
piece of code that perceives (gathers facts from the database and files),
decides (rules, plus the model wherever reading or drafting is needed), and
acts - either doing something or proposing it for a person to approve. The
model reads and writes; the code computes and chooses; the buyer decides.

That division is deliberate. Nothing in a sourcing case should be settled by
a model's judgement - which offer is cheapest, whether a document is signed,
whether a case may close - and in this design nothing is, because no agent
ever hands the model that question.

Every run writes a row to agent_runs with its full perceive / decide / act
log. That log is what lets someone check what an agent did rather than trust
that it did something.
"""

import logging
import traceback
from datetime import datetime

import db

logger = logging.getLogger("sourceflow.agents")

REGISTRY = {}


def register(cls):
    REGISTRY[cls.key] = cls
    return cls


class RunLog:
    """Collects the three phases as the agent works, then becomes the
    `detail` column. Kept as a list of lines rather than a string so an agent
    can log as it goes and a crash still leaves a readable partial log."""

    def __init__(self):
        self.lines = []

    def perceive(self, text):  self.lines.append(f"PERCEIVE  {text}")
    def decide(self, text):    self.lines.append(f"DECIDE    {text}")
    def act(self, text):       self.lines.append(f"ACT       {text}")
    def note(self, text):      self.lines.append(f"          {text}")

    def text(self):
        return "\n".join(self.lines)


class Agent:
    """Subclass, set the class attributes, implement run(log, **kwargs).

    run() returns (status, summary, subject):
        status   ok | nothing | error   - "nothing" is a real outcome: the
                                          agent looked and found no work
        summary  one line for the list
        subject  what it worked on, e.g. "SF-2026-00003" or "RFQ-20260917-2102"
    """

    key = ""            # url-safe identifier
    name = ""           # shown in the UI
    tagline = ""        # what it does, one line
    perceives = ""      # what it looks at
    acts = ""           # what it does about it
    uses_llm = False    # whether the model is involved at all

    def run(self, log: RunLog, **kwargs):
        raise NotImplementedError

    def execute(self, trigger="manual", actor="system", **kwargs) -> dict:
        """Runs the agent and records the run, whatever happens. Never raises:
        an agent failing must show up as a failed run in the log, not as a
        500 in whatever screen happened to trigger it."""
        started = datetime.now().isoformat(timespec="seconds")
        log = RunLog()
        try:
            status, summary, subject = self.run(log, **kwargs)
        except Exception as exc:                      # noqa: BLE001 - see docstring
            logger.exception("Agent %s failed", self.key)
            status, summary, subject = "error", f"{type(exc).__name__}: {exc}", kwargs.get("subject")
            log.note("TRACEBACK")
            log.note(traceback.format_exc().strip())

        run_id = db.insert_agent_run(self.key, trigger, actor, subject, status, summary,
                                     log.text(), started)
        return {"id": run_id, "agent": self.key, "status": status, "summary": summary,
                "subject": subject, "detail": log.text()}


def get(key: str) -> Agent:
    cls = REGISTRY.get(key)
    return cls() if cls else None


def all_agents() -> list:
    return [cls() for cls in REGISTRY.values()]
