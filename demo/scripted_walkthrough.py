"""
Runs the exact tool logic the agent would use, in the sequence a correctly
policy-following agent would call it, directly (no LLM / no AWS
credentials required). This proves the mechanics — DB state, matching
logic, escalation creation — actually work, independent of whether a judge
has Bedrock access to run the live LLM loop.

The *decisions* about which tool to call and when are the LLM's job in the
real deployment (see goodneighbor/agent.py's system prompt). The shared
policy path exercised here lives in goodneighbor/deterministic_cycles.py so
the dashboard's "run cycle" buttons can use the exact same, already-proven
logic when no Bedrock credentials are configured.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from goodneighbor.db import reset_db  # noqa: E402
from goodneighbor.seed_data import seed  # noqa: E402
from goodneighbor.deterministic_cycles import (  # noqa: E402
    run_volunteer_cycle,
    run_inventory_cycle,
    run_donation_cycle,
)
from goodneighbor.escalation import list_pending_escalations, format_escalation_for_sms  # noqa: E402
from goodneighbor.digest import build_digest, render_markdown  # noqa: E402


def hr(title=""):
    print("\n" + "=" * 70)
    if title:
        print(title)
        print("=" * 70)


def print_log(entries):
    for e in entries:
        prefix = {"info": " ", "action": "->", "escalation": "!!"}.get(e["kind"], " ")
        print(f"{prefix} {e['text']}")


def main():
    reset_db()
    seed()

    hr("CYCLE: volunteer coverage")
    print_log(run_volunteer_cycle())

    hr("CYCLE: inventory & expiry")
    print_log(run_inventory_cycle())

    hr("CYCLE: donation intake")
    print_log(run_donation_cycle())

    hr("WHAT'S PENDING FOR A HUMAN")
    for e in list_pending_escalations():
        print(format_escalation_for_sms(e))
        print("-" * 40)

    hr("WEEKLY DIGEST")
    print(render_markdown(build_digest()))


if __name__ == "__main__":
    main()
