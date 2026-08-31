"""Shift coverage monitoring and backup-recruiting tools."""

from datetime import date, timedelta

from strands import tool

from ..db import get_conn, log_activity, rows_to_dicts
from ..config import COVERAGE_LOOKAHEAD_DAYS


@tool
def get_shift_coverage(days_ahead: int = COVERAGE_LOOKAHEAD_DAYS) -> list:
    """Get upcoming shifts within the lookahead window along with how many
    confirmed volunteers each has versus how many are needed.

    Args:
        days_ahead: How many days ahead to look (defaults to policy window).

    Returns:
        A list of shifts, each with id, role, shift_date, start_time,
        end_time, location, needed_count, confirmed_count, and gap
        (needed_count - confirmed_count; 0 or negative means fully covered).
    """
    horizon = (date.today() + timedelta(days=days_ahead)).isoformat()
    with get_conn() as conn:
        shifts = conn.execute(
            "SELECT * FROM shifts WHERE shift_date >= date('now') AND shift_date <= ? "
            "ORDER BY shift_date ASC",
            (horizon,),
        ).fetchall()
        result = []
        for s in shifts:
            confirmed = conn.execute(
                "SELECT COUNT(*) AS c FROM shift_assignments WHERE shift_id = ? AND status = 'confirmed'",
                (s["id"],),
            ).fetchone()["c"]
            row = dict(s)
            row["confirmed_count"] = confirmed
            row["gap"] = row["needed_count"] - confirmed
            result.append(row)
    return result


@tool
def find_available_backup_volunteers(shift_id: int, required_skill: str = "") -> list:
    """Find backup-pool volunteers who are not already assigned somewhere
    on the same date as the given shift, optionally filtered to a required
    skill (e.g. "driving" for a truck pickup shift).

    Args:
        shift_id: The shift to find coverage for.
        required_skill: Optional skill tag that must appear in the
            volunteer's skills (e.g. "driving"). Leave blank for no filter.

    Returns:
        A list of candidate volunteers sorted by reliability_score
        descending, each with id, name, phone, skills, reliability_score.
    """
    with get_conn() as conn:
        shift = conn.execute("SELECT * FROM shifts WHERE id = ?", (shift_id,)).fetchone()
        if not shift:
            return []
        already_busy = {
            r["volunteer_id"]
            for r in conn.execute(
                "SELECT sa.volunteer_id FROM shift_assignments sa "
                "JOIN shifts s ON s.id = sa.shift_id "
                "WHERE s.shift_date = ? AND sa.status = 'confirmed'",
                (shift["shift_date"],),
            ).fetchall()
        }
        candidates = conn.execute(
            "SELECT * FROM volunteers WHERE is_backup = 1 AND active = 1 "
            "ORDER BY reliability_score DESC"
        ).fetchall()
    out = []
    for c in candidates:
        if c["id"] in already_busy:
            continue
        skills = (c["skills"] or "").split(",")
        if required_skill and required_skill not in skills:
            continue
        out.append(dict(c))
    return out


@tool
def notify_volunteer(volunteer_id: int, message: str) -> str:
    """Send a shift-related message to a volunteer (simulated: logs the
    outbound notification; wire to real SMS/email in production). Use this
    when contacting a backup volunteer to ask them to cover a gap.

    Args:
        volunteer_id: The volunteer to contact.
        message: The message to send them.

    Returns:
        A simulated delivery confirmation.
    """
    with get_conn() as conn:
        v = conn.execute("SELECT name, phone FROM volunteers WHERE id = ?", (volunteer_id,)).fetchone()
    if not v:
        return f"No volunteer with id {volunteer_id}."
    log_activity("agent", "notify_volunteer", f"To {v['name']} ({v['phone']}): {message}")
    return f"Message sent to {v['name']}: \"{message}\" (simulated SMS to {v['phone']})."


@tool
def assign_volunteer_to_shift(shift_id: int, volunteer_id: int) -> str:
    """Confirm a volunteer's assignment to a shift after they've accepted
    (e.g. after find_available_backup_volunteers + notify_volunteer).
    Only call this once the volunteer has actually agreed — do not assign
    speculatively.

    Args:
        shift_id: The shift being filled.
        volunteer_id: The volunteer who accepted.

    Returns:
        Confirmation and the shift's updated coverage.
    """
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO shift_assignments (shift_id, volunteer_id, status, assigned_by) "
            "VALUES (?, ?, 'confirmed', 'agent')",
            (shift_id, volunteer_id),
        )
        v = conn.execute("SELECT name FROM volunteers WHERE id = ?", (volunteer_id,)).fetchone()
        shift = conn.execute("SELECT * FROM shifts WHERE id = ?", (shift_id,)).fetchone()
        confirmed = conn.execute(
            "SELECT COUNT(*) AS c FROM shift_assignments WHERE shift_id = ? AND status = 'confirmed'",
            (shift_id,),
        ).fetchone()["c"]
    log_activity(
        "agent", "assign_volunteer_to_shift",
        f"{v['name']} -> shift #{shift_id} ({shift['role']} on {shift['shift_date']})",
    )
    gap = shift["needed_count"] - confirmed
    return (
        f"{v['name']} confirmed for shift #{shift_id} ({shift['role']}, {shift['shift_date']}). "
        f"Coverage now {confirmed}/{shift['needed_count']}"
        + (", fully staffed." if gap <= 0 else f", still short {gap}.")
    )
