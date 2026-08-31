"""
Cross-cutting operational tools.

`escalate_to_human` is the single, deliberate channel through which the
agent is allowed to surface a decision to a person. Every other tool acts;
this one asks.
"""

import json
from datetime import datetime

from strands import tool

from ..db import get_conn, log_activity


@tool
def get_current_datetime() -> str:
    """Get the current date and time (ISO 8601, UTC). Use this before any
    date-comparison reasoning about shifts or expiry dates so 'today' and
    'in N days' are computed correctly rather than assumed.
    """
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


@tool
def escalate_to_human(
    title: str,
    description: str,
    category: str,
    options: list,
    urgency: str = "normal",
) -> str:
    """Raise a decision to a human coordinator instead of deciding autonomously.

    Use this ONLY when the situation genuinely needs human judgment: a safety
    concern, a resource conflict between competing needs, a threshold breach
    defined by policy, or real ambiguity where no option is clearly correct.
    Do not use this for routine actions you are authorized to take yourself —
    take the action and log it instead.

    Args:
        title: A short, specific summary a coordinator can read at a glance
            (e.g. "Truck pickup shift on Sat still short one driver").
        description: 2-4 sentences of context: what happened, why it needs a
            person, and what you already tried.
        category: One of "coverage", "inventory", or "donation".
        options: A list of 2-3 concrete options, each a short string a
            coordinator could pick by replying with its number
            (e.g. ["Approve routing 40 lbs peppers to Riverside Fridge",
            "Split 20/20 between Fridge and Elmwood Shelter",
            "Decline and notify donor pickup isn't possible"]).
        urgency: One of "low", "normal", "high". Use "high" only when a
            decision is needed within hours (e.g. same-day perishable pickup
            or a shift starting within the escalation window).

    Returns:
        Confirmation including the escalation id.
    """
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO escalations (category, title, description, options_json, urgency) "
            "VALUES (?, ?, ?, ?, ?)",
            (category, title, description, json.dumps(options), urgency),
        )
        escalation_id = cur.lastrowid
    log_activity(
        "agent",
        "escalate_to_human",
        f"[{category}/{urgency}] {title}",
        autonomous=False,
    )
    return (
        f"Escalation #{escalation_id} created and will be sent to the coordinator "
        f"(urgency: {urgency}). Do not take the underlying action yourself; wait for resolution."
    )


@tool
def notify_coordinator(message: str, channel: str = "digest") -> str:
    """Send a low-priority informational note to the human coordinator that
    does NOT require a decision (e.g. "filled Saturday's shift from backups").
    Use this to keep the coordinator informed without interrupting them —
    it lands in the passive weekly digest by default, not a push notification.

    Args:
        message: The informational note.
        channel: "digest" (default, batched weekly) or "immediate" (rare —
            only for something a coordinator would want to know same-day even
            though no decision is needed, e.g. a large clean donation match).

    Returns:
        Confirmation the note was recorded.
    """
    log_activity("agent", f"notify_coordinator[{channel}]", message, autonomous=True)
    return f"Noted for coordinator via '{channel}'."
