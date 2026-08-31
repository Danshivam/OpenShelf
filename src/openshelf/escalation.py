"""Helpers for reading and resolving the human escalation queue.

This is the entire "interface" a coordinator needs: a short list of pending
decisions, each with concrete options, and a one-line way to resolve one.
"""

import json
from datetime import datetime

from .db import get_conn, log_activity, rows_to_dicts


def list_pending_escalations() -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM escalations WHERE status = 'pending' "
            "ORDER BY CASE urgency WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END, created_at ASC"
        ).fetchall()
    out = rows_to_dicts(rows)
    for r in out:
        r["options"] = json.loads(r["options_json"]) if r["options_json"] else []
    return out


def resolve_escalation(escalation_id: int, resolution: str, resolved_by: str = "coordinator") -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM escalations WHERE id = ?", (escalation_id,)).fetchone()
        if not row:
            raise ValueError(f"No escalation with id {escalation_id}")
        conn.execute(
            "UPDATE escalations SET status = 'resolved', resolved_at = ?, resolution = ? WHERE id = ?",
            (datetime.utcnow().isoformat(timespec="seconds"), resolution, escalation_id),
        )
    log_activity(resolved_by, "resolve_escalation", f"#{escalation_id}: {resolution}", autonomous=False)
    return {"id": escalation_id, "status": "resolved", "resolution": resolution}


def format_escalation_for_sms(escalation: dict) -> str:
    """Render a single escalation as a short push/SMS-style message —
    what actually reaches a coordinator's phone in production."""
    lines = [f"[{escalation['urgency'].upper()}] {escalation['title']}", "", escalation["description"], ""]
    for i, opt in enumerate(escalation.get("options", []), start=1):
        lines.append(f"{i}. {opt}")
    lines.append("")
    lines.append(f"Reply with a number, or open the digest for full context. (#{escalation['id']})")
    return "\n".join(lines)
