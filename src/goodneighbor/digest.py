"""
Builds the periodic digest: the *only* thing a coordinator is expected to
read on a normal week. Everything the agent handled autonomously, rolled up
by category, plus what's still pending a decision.
"""

from collections import Counter
from datetime import datetime, timedelta

from . import config
from .db import get_conn, rows_to_dicts
from .escalation import list_pending_escalations


def _recent_autonomous_actions(since: datetime) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM activity_log WHERE autonomous = 1 AND actor = 'agent' "
            "AND timestamp >= ? ORDER BY timestamp ASC",
            (since.isoformat(timespec="seconds"),),
        ).fetchall()
    return rows_to_dicts(rows)


def build_digest(period_days: int = 7) -> dict:
    since = datetime.utcnow() - timedelta(days=period_days)
    actions = _recent_autonomous_actions(since)
    by_action = Counter(a["action"] for a in actions)
    pending = list_pending_escalations()
    return {
        "org_name": config.ORG_NAME,
        "period_days": period_days,
        "generated_at": datetime.utcnow().isoformat(timespec="seconds"),
        "total_autonomous_actions": len(actions),
        "actions_by_type": dict(by_action),
        "actions": actions,
        "pending_escalations": pending,
    }


def render_markdown(digest: dict) -> str:
    lines = [
        f"# Good Neighbor Agent — Weekly Digest",
        f"**{digest['org_name']}** · last {digest['period_days']} days · generated {digest['generated_at']} UTC",
        "",
        f"Handled **{digest['total_autonomous_actions']}** things on its own this week. "
        f"You have **{len(digest['pending_escalations'])}** decision(s) waiting.",
        "",
    ]

    if digest["pending_escalations"]:
        lines.append("## Needs your call")
        for e in digest["pending_escalations"]:
            lines.append(f"- **[{e['urgency'].upper()}] {e['title']}** (#{e['id']})")
            lines.append(f"  {e['description']}")
            for i, opt in enumerate(e["options"], start=1):
                lines.append(f"  {i}. {opt}")
        lines.append("")

    if digest["actions_by_type"]:
        lines.append("## Handled automatically")
        for action, count in sorted(digest["actions_by_type"].items(), key=lambda kv: -kv[1]):
            lines.append(f"- {action.replace('_', ' ')}: {count}")
        lines.append("")
        lines.append("<details><summary>Full activity log</summary>\n")
        for a in digest["actions"]:
            lines.append(f"- `{a['timestamp']}` {a['action']}: {a['detail']}")
        lines.append("\n</details>")
    else:
        lines.append("Nothing to report — a quiet week.")

    return "\n".join(lines)


def render_html(digest: dict) -> str:
    pending_html = "".join(
        f"<li><strong>[{e['urgency'].upper()}] {e['title']}</strong> (#{e['id']})"
        f"<p>{e['description']}</p><ol>"
        + "".join(f"<li>{opt}</li>" for opt in e["options"])
        + "</ol></li>"
        for e in digest["pending_escalations"]
    ) or "<p>Nothing pending.</p>"

    actions_html = "".join(
        f"<li>{action.replace('_', ' ')}: {count}</li>"
        for action, count in sorted(digest["actions_by_type"].items(), key=lambda kv: -kv[1])
    ) or "<p>Nothing to report — a quiet week.</p>"

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Good Neighbor Agent Digest</title>
<style>
body {{ font-family: -apple-system, Segoe UI, sans-serif; max-width: 640px; margin: 40px auto; color: #1a1a1a; }}
h1 {{ font-size: 1.3rem; }} h2 {{ font-size: 1.05rem; margin-top: 2rem; border-bottom: 1px solid #eee; padding-bottom: .3rem;}}
.summary {{ background: #f6f8fa; padding: 12px 16px; border-radius: 8px; }}
li {{ margin-bottom: .6rem; }}
</style></head>
<body>
<h1>Good Neighbor Agent — Weekly Digest</h1>
<p><strong>{digest['org_name']}</strong> · last {digest['period_days']} days</p>
<div class="summary">Handled <strong>{digest['total_autonomous_actions']}</strong> things on its own this week.
You have <strong>{len(digest['pending_escalations'])}</strong> decision(s) waiting.</div>
<h2>Needs your call</h2>
<ul>{pending_html}</ul>
<h2>Handled automatically</h2>
<ul>{actions_html}</ul>
</body></html>"""
