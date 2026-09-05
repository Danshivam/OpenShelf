"""
Bedrock AgentCore Runtime entrypoint for OpenShelf.

This is the ONLY thing AWS invokes. There is no chat UI behind it — its
callers are:

1. Amazon EventBridge Scheduler, on a fixed cadence, invoking one of the
   background cycles ({"mode": "cycle", "cycle": "volunteers"|"inventory"|"donations"}).
2. A coordinator resolving an escalation from an SMS/Slack reply
   ({"mode": "resolve_escalation", "escalation_id": 12, "resolution": "..."}).
3. An ad-hoc operator prompt for debugging ({"mode": "prompt", "prompt": "..."}).

Run locally with `python agentcore/app.py` (serves http://localhost:8080,
POST to /invocations) or deploy with the AgentCore starter toolkit /
Dockerfile in this directory. See deploy.md for the full path to production,
including the EventBridge schedules and escalation delivery wiring.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bedrock_agentcore import BedrockAgentCoreApp  # noqa: E402

from openshelf.orchestrator import run_cycle, run_all_cycles  # noqa: E402
from openshelf.escalation import resolve_escalation, list_pending_escalations  # noqa: E402
from openshelf.digest import build_digest, render_markdown  # noqa: E402
from openshelf.agent import build_agent  # noqa: E402
from openshelf.db import init_db  # noqa: E402

app = BedrockAgentCoreApp()

# Ensure the schema exists on cold start (idempotent; seeding is a separate,
# explicit step done once via the CLI, not on every invocation).
init_db()


@app.entrypoint
def invoke(payload: dict) -> dict:
    """Single entrypoint for all invocation modes. `payload` is the JSON
    body AgentCore forwards from InvokeAgentRuntime."""
    mode = payload.get("mode", "prompt")

    if mode == "cycle":
        cycle = payload.get("cycle", "all")
        if cycle == "all":
            summaries = run_all_cycles()
        else:
            summaries = {cycle: run_cycle(cycle)}
        return {"mode": "cycle", "results": summaries}

    if mode == "resolve_escalation":
        result = resolve_escalation(
            escalation_id=payload["escalation_id"],
            resolution=payload["resolution"],
            resolved_by=payload.get("resolved_by", "coordinator"),
        )
        return {"mode": "resolve_escalation", "result": result}

    if mode == "digest":
        digest = build_digest(period_days=payload.get("days", 7))
        return {"mode": "digest", "markdown": render_markdown(digest), "digest": digest}

    if mode == "list_escalations":
        return {"mode": "list_escalations", "pending": list_pending_escalations()}

    # mode == "prompt": ad-hoc operator/debugging access to the live agent.
    agent = build_agent()
    prompt = payload.get("prompt", "Summarize current status across all cycles without taking action.")
    result = agent(prompt)
    return {"mode": "prompt", "response": str(result)}


if __name__ == "__main__":
    app.run()
