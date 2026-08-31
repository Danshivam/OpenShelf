"""
The orchestrator turns "the agent" into a set of independent background
cycles, each a single focused task the agent reasons through with its
tools. In production these are triggered by EventBridge Scheduler rules
(see agentcore/deploy.md) rather than a loop in this process — the loop
here exists for local/dev use and for the CLI demo.
"""

import time
from datetime import datetime

from .agent import build_agent
from .db import log_activity

CYCLE_PROMPTS = {
    "volunteers": (
        "Run the volunteer coverage cycle. Check shift coverage for the "
        "policy lookahead window, fill any gaps you're authorized to fill "
        "from the backup pool, and escalate anything you can't safely fill. "
        "Summarize what you checked, filled, and escalated."
    ),
    "inventory": (
        "Run the inventory & expiry cycle. Check inventory status, route "
        "any perishable items nearing expiry that you're authorized to "
        "route on your own, flag low-stock non-perishables for reorder via "
        "notify_coordinator, and escalate anything above policy thresholds "
        "or with no safe recipient. Summarize what you checked, routed, and escalated."
    ),
    "donations": (
        "Run the donation intake cycle. Review open donation offers, match "
        "each to a partner org, auto-route the ones that are a clean match "
        "within policy, and escalate the ones that require judgment. "
        "Summarize what you checked, routed, and escalated."
    ),
}

CYCLE_INTERVAL_SECONDS = {
    "volunteers": 4 * 60 * 60,   # every 4 hours
    "inventory": 24 * 60 * 60,   # daily
    "donations": 30 * 60,        # every 30 minutes (time-sensitive, perishable)
}


def run_cycle(cycle: str, agent=None) -> str:
    """Run one named cycle ('volunteers' | 'inventory' | 'donations') and
    return the agent's summary. Builds a fresh agent if none is passed."""
    if cycle not in CYCLE_PROMPTS:
        raise ValueError(f"Unknown cycle '{cycle}'. Options: {list(CYCLE_PROMPTS)}")
    agent = agent or build_agent()
    log_activity("system", "cycle_start", cycle, autonomous=False)
    result = agent(CYCLE_PROMPTS[cycle])
    log_activity("system", "cycle_end", cycle, autonomous=False)
    return str(result)


def run_all_cycles(agent=None) -> dict:
    agent = agent or build_agent()
    return {cycle: run_cycle(cycle, agent=agent) for cycle in CYCLE_PROMPTS}


def run_scheduler_loop(poll_seconds: int = 60) -> None:
    """A minimal always-on scheduler for local/dev use. In production, use
    EventBridge Scheduler to invoke the AgentCore Runtime endpoint per
    cycle instead of keeping a process alive (see agentcore/deploy.md)."""
    agent = build_agent()
    last_run = {cycle: 0.0 for cycle in CYCLE_PROMPTS}
    print(f"[{datetime.utcnow().isoformat()}] Good Neighbor Agent scheduler starting.")
    while True:
        now = time.time()
        for cycle, interval in CYCLE_INTERVAL_SECONDS.items():
            if now - last_run[cycle] >= interval:
                print(f"[{datetime.utcnow().isoformat()}] Running cycle: {cycle}")
                try:
                    summary = run_cycle(cycle, agent=agent)
                    print(summary)
                except Exception as exc:  # pragma: no cover - defensive for a long-lived loop
                    log_activity("system", "cycle_error", f"{cycle}: {exc}", autonomous=False)
                    print(f"Cycle {cycle} failed: {exc}")
                last_run[cycle] = now
        time.sleep(poll_seconds)
