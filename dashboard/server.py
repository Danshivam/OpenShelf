"""
Good Neighbor Agent — dashboard backend.

A thin Flask API over the exact same modules the agent itself uses
(goodneighbor.db / escalation / digest / tools). There is no separate
"dashboard data model" — resolving an escalation here is the same action
the agent's own tools would see on its next cycle, and the activity feed
is the literal activity_log table the agent writes to.

Run:
    python dashboard/server.py
Then open http://localhost:5050
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from flask import Flask, jsonify, request, send_from_directory

from goodneighbor import config
from goodneighbor.db import get_conn, rows_to_dicts, init_db
from goodneighbor.escalation import list_pending_escalations, resolve_escalation
from goodneighbor.digest import build_digest
from goodneighbor.deterministic_cycles import CYCLE_FUNCS

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")

init_db()  # idempotent — safe if the DB already exists and is seeded


# ---------------------------------------------------------------------------
# Static frontend
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------

@app.get("/api/status")
def api_status():
    digest = build_digest(period_days=7)
    with get_conn() as conn:
        volunteer_count = conn.execute("SELECT COUNT(*) c FROM volunteers WHERE active=1").fetchone()["c"]
        shift_count = conn.execute(
            "SELECT COUNT(*) c FROM shifts WHERE shift_date >= date('now')"
        ).fetchone()["c"]
        partner_count = conn.execute("SELECT COUNT(*) c FROM partner_orgs").fetchone()["c"]
        open_offers = conn.execute(
            "SELECT COUNT(*) c FROM donation_offers WHERE status='open'"
        ).fetchone()["c"]
    return jsonify({
        "org_name": config.ORG_NAME,
        "pending_count": len(digest["pending_escalations"]),
        "autonomous_count": digest["total_autonomous_actions"],
        "actions_by_type": digest["actions_by_type"],
        "volunteer_count": volunteer_count,
        "upcoming_shift_count": shift_count,
        "partner_count": partner_count,
        "open_donation_offers": open_offers,
        "generated_at": digest["generated_at"],
    })


@app.get("/api/escalations")
def api_escalations():
    return jsonify(list_pending_escalations())


@app.get("/api/digest")
def api_digest():
    days = int(request.args.get("days", 7))
    return jsonify(build_digest(period_days=days))


@app.get("/api/activity")
def api_activity():
    limit = int(request.args.get("limit", 25))
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM activity_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return jsonify(rows_to_dicts(rows))


@app.get("/api/shifts")
def api_shifts():
    from goodneighbor.tools.volunteer_tools import get_shift_coverage
    return jsonify(get_shift_coverage())


@app.get("/api/inventory")
def api_inventory():
    from goodneighbor.tools.inventory_tools import get_inventory_status
    return jsonify(get_inventory_status())


@app.get("/api/donations")
def api_donations():
    from goodneighbor.tools.donation_tools import list_open_donation_offers
    return jsonify(list_open_donation_offers())


@app.get("/api/partners")
def api_partners():
    from goodneighbor.tools.donation_tools import get_partner_orgs
    return jsonify(get_partner_orgs())


# ---------------------------------------------------------------------------
# Write / action endpoints
# ---------------------------------------------------------------------------

@app.post("/api/escalations/<int:escalation_id>/resolve")
def api_resolve(escalation_id):
    body = request.get_json(force=True, silent=True) or {}
    resolution = body.get("resolution", "Resolved from dashboard")
    try:
        result = resolve_escalation(escalation_id, resolution, resolved_by=body.get("resolved_by", "coordinator"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    return jsonify(result)


@app.post("/api/cycles/<cycle>/run")
def api_run_cycle(cycle):
    """Run a background cycle now. Prefers the real Strands agent (needs
    Bedrock credentials); falls back to the deterministic policy path
    (goodneighbor.deterministic_cycles) if that's unavailable, so this
    button always works, but tells you honestly which engine ran."""
    if cycle not in CYCLE_FUNCS:
        return jsonify({"error": f"Unknown cycle '{cycle}'"}), 400

    try:
        from goodneighbor.orchestrator import run_cycle
        summary = run_cycle(cycle)
        return jsonify({"engine": "llm-agent", "cycle": cycle, "summary": summary})
    except Exception as exc:  # no Bedrock creds, no model access, network error, etc.
        entries = CYCLE_FUNCS[cycle]()
        return jsonify({
            "engine": "deterministic-fallback",
            "cycle": cycle,
            "note": f"Ran the deterministic policy path — real agent unavailable ({exc.__class__.__name__}).",
            "log": entries,
        })


@app.post("/api/reset-demo")
def api_reset_demo():
    from goodneighbor.db import reset_db
    from goodneighbor.seed_data import seed
    reset_db()
    seed()
    return jsonify({"status": "reset"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    print(f"Good Neighbor Agent dashboard running at http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
