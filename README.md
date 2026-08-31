# Good Neighbor Agent

**Track:** Good Neighbor Agents — agents that help *groups* of people (neighborhoods, nonprofits, food banks, schools, libraries, small local orgs).
**Built with:** [Strands Agents SDK](https://strandsagents.com) · **Deployed on:** Amazon Bedrock AgentCore Runtime

## The problem

Small community organizations — food banks, mutual aid networks, shelters — run on the same handful of overworked coordinators. Every week they re-solve the same three problems by hand:

1. **"Is Saturday's shift actually covered?"** — chasing volunteers over text.
2. **"What's about to expire, and who can take it before it spoils?"** — checking a spreadsheet, then calling around.
3. **"Someone just offered us 200 lbs of produce — who should get it?"** — a judgment call made under time pressure, usually by whoever picks up the phone.

None of this needs a new dashboard. Coordinators don't want *another app to check*. They want the routine 80% handled quietly, and to be pulled in only for the 20% that actually needs a human judgment call — a safety concern, a resource conflict, a threshold breach, or genuine ambiguity.

## What this is

A single autonomous agent — **the Good Neighbor Agent** — that runs on a schedule in the background for a community org (demo scenario: **Riverside Community Food Bank**), watching three things:

| Cycle | What it checks | What it does on its own | What it escalates |
|---|---|---|---|
| **Volunteer coverage** | Shifts in the next N days vs. confirmed headcount | Recruits from the backup volunteer pool and auto-confirms fills | A shift stays uncovered past the safe window, or no backups exist |
| **Inventory & expiry** | Stock levels vs. thresholds, expiry dates | Logs low-stock items for reorder, routes near-expiry perishables to a partner org with capacity | Large-value shortfall, no safe recipient found, or a food-safety flag |
| **Donation intake** | New donation offers vs. partner org need/capacity | Auto-confirms a clean match (one clear best recipient with capacity) | Competing high-need recipients, unusual/large donations, allergen or condition concerns |

Everything the agent does autonomously is written to an activity log and rolled into a **weekly digest** — a two-minute read, not a dashboard to babysit. Everything that needs a person becomes a single, specific **escalation**: a title, the situation, and 2–3 concrete options, sent to the coordinator's phone. No back-and-forth, no interface to learn.

This is the core design bet: **the agent is judged by how rarely it needs you, and how good the ask is when it does.**

## Why Strands, non-trivially

The agent is not a thin prompt wrapper. It is a single `strands.Agent` given real tools backed by a real SQLite datastore (volunteers, shifts, inventory, partner orgs, donation offers, escalations, activity log — see `src/goodneighbor/db.py`), and a system prompt that encodes an explicit **autonomy policy**: what it's allowed to decide alone, and what it must hand to a human, with the `escalate_to_human` tool as the one and only channel for surfacing a decision. The agent has to reason about ambiguity, competing constraints, and thresholds using the tool outputs — it isn't following a fixed script. See `src/goodneighbor/agent.py` for the system prompt and tool wiring, and `src/goodneighbor/orchestrator.py` for how each cycle is triggered as an independent task.

## Project layout

```
src/goodneighbor/
  config.py            # thresholds & policy constants (the "autonomy contract")
  db.py                # SQLite schema + helpers, activity logging
  seed_data.py          # realistic one-week demo scenario for Riverside Community Food Bank
  deterministic_cycles.py  # non-LLM implementation of the policy, shared by the CLI demo and dashboard
  tools/
    inventory_tools.py  # inventory + donation intake tools
    volunteer_tools.py  # shift coverage + backup recruiting tools
    donation_tools.py   # partner-org matching + routing tools
    ops_tools.py         # escalate_to_human, notifications, clock
  agent.py              # builds the Strands Agent (system prompt + tools)
  orchestrator.py       # the background cycles + simple scheduler
  digest.py             # weekly digest (markdown + HTML)
  escalation.py         # escalation queue helpers
  cli.py                # `python -m goodneighbor.cli ...` demo/ops CLI
agentcore/
  app.py                # BedrockAgentCoreApp entrypoint for AgentCore Runtime
  Dockerfile
  deploy.md             # deployment + scheduling instructions
dashboard/
  server.py             # Flask API over the same db/tools/escalation/digest modules
  static/                # matte-themed frontend (index.html, style.css, app.js)
demo/
  scripted_walkthrough.py  # runs the real tool logic end-to-end, no AWS creds needed
  demo_transcript.md        # captured output of the walkthrough, for judges
tests/
  test_tools.py
```

## Running it

```bash
pip install -r requirements.txt

# 1. Build the demo world
python -m goodneighbor.cli init-db
python -m goodneighbor.cli seed

# 2. Prove the tool logic end-to-end (no AWS credentials required)
python demo/scripted_walkthrough.py

# 3. Open the dashboard — this is the presentable, clickable view for a demo
python dashboard/server.py
# then open http://localhost:5050

# 4. Run a real agentic cycle from the CLI (requires AWS credentials with Bedrock access)
export AWS_REGION=us-east-1
python -m goodneighbor.cli run-cycle all

# 5. Inspect what needs a human
python -m goodneighbor.cli show-escalations
python -m goodneighbor.cli digest
```

## The dashboard

`dashboard/server.py` is a thin Flask API over the *exact same* modules the
agent itself uses — `goodneighbor.db`, `escalation`, `digest`, and the tool
functions. There's no separate dashboard data model: resolving an
escalation in the browser is the same `resolve_escalation()` call the CLI
and the agent's own next cycle would see.

The design is deliberately quiet rather than dashboard-y: a matte, muted
palette (olive/clay/mustard/brick on a warm parchment base), category
colour carried by a bar rather than icons, and the "Needs your call" queue
as the dominant element — because that's the one thing a coordinator is
ever actually asked to look at. Each escalation renders its options as
numbered buttons, mirroring the real SMS format
(`escalation.format_escalation_for_sms`) a coordinator would get in
production. A "Run a cycle now" panel lets you trigger any of the three
background cycles on demand: it prefers the real Strands agent (if Bedrock
credentials are configured) and otherwise falls back to the same
deterministic policy path used by `demo/scripted_walkthrough.py`, labeling
honestly which one ran.



## Deploying to Bedrock AgentCore

See `agentcore/deploy.md`. In short: `agentcore/app.py` wraps the same agent from `goodneighbor.agent` in a `BedrockAgentCoreApp`, containerized via `agentcore/Dockerfile`, and invoked on a schedule by Amazon EventBridge Scheduler (one rule per cycle) rather than by a person opening an app. Escalations are pushed out over SNS/Slack webhook — the only time the org actually hears from the agent unprompted.

## Judging criteria, mapped

- **Technological implementation** — a real `strands.Agent` with 13 purpose-built tools over a real relational datastore, explicit autonomy/escalation policy in the system prompt, a working AgentCore Runtime entrypoint (`agentcore/app.py`, tested locally against the real `bedrock_agentcore` server), and a deterministic tool-logic path that runs without any AWS dependency to prove the mechanics — reused by both the CLI demo and the dashboard's live "run cycle" buttons.
- **Design** — the product is designed around *not* being opened: scheduled background cycles, a once-a-week digest, and single, specific escalations instead of a chat UI to manage. The dashboard exists as a presentable window into that system, not the product itself — its whole layout is built around making the "needs your call" queue the dominant, unmissable element, exactly mirroring the SMS-style escalation format the backend already produces.
- **Potential impact** — targets a named, common failure mode (volunteer no-shows, spoiled donations, mismatched donation routing) for a concrete audience (food banks / mutual aid orgs) with a measurable output: fewer uncovered shifts, less wasted food, faster donation routing, and a bounded number of decisions actually asked of a human.

