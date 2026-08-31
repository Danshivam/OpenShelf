"""Donation offer matching and routing to partner organizations."""

from strands import tool

from ..db import get_conn, log_activity, rows_to_dicts


@tool
def list_open_donation_offers() -> list:
    """List donation offers that haven't been routed or escalated yet.

    Returns:
        A list of open donation offers with id, donor_name, item_name,
        category, quantity, unit, perishable, condition_notes, pickup_window.
    """
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM donation_offers WHERE status = 'open' ORDER BY offered_at ASC"
        ).fetchall()
    return rows_to_dicts(rows)


@tool
def get_partner_orgs(category: str = "") -> list:
    """Get partner organizations that can receive donations, optionally
    filtered to ones that accept a given category, with remaining weekly
    capacity computed for you.

    Args:
        category: Optional category filter (e.g. "produce", "dairy").
            Leave blank to list all partners.

    Returns:
        A list of partner orgs with id, name, org_type, accepts_categories,
        weekly_capacity_units, current_intake_units, remaining_capacity,
        distance_km, and high_need (bool).
    """
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM partner_orgs").fetchall()
    out = []
    for r in rows:
        accepted = (r["accepts_categories"] or "").split(",")
        if category and category not in accepted:
            continue
        row = dict(r)
        row["remaining_capacity"] = row["weekly_capacity_units"] - row["current_intake_units"]
        row["high_need"] = bool(row["high_need"])
        out.append(row)
    return out


@tool
def route_donation_to_partner(offer_id: int, partner_org_id: int) -> str:
    """Confirm routing a donation offer to a specific partner org: marks the
    offer routed, deducts capacity from the partner, and logs the pickup
    plan. Only call this once you've decided (autonomously, within policy)
    or a human has approved the routing via an escalation.

    Args:
        offer_id: The donation offer being routed.
        partner_org_id: The partner org that will receive it.

    Returns:
        Confirmation of the routing, including the partner's remaining capacity.
    """
    with get_conn() as conn:
        offer = conn.execute("SELECT * FROM donation_offers WHERE id = ?", (offer_id,)).fetchone()
        partner = conn.execute("SELECT * FROM partner_orgs WHERE id = ?", (partner_org_id,)).fetchone()
        if not offer or not partner:
            return "Offer or partner org not found."
        conn.execute(
            "UPDATE donation_offers SET status = 'routed', routed_to_partner_id = ? WHERE id = ?",
            (partner_org_id, offer_id),
        )
        new_intake = partner["current_intake_units"] + offer["quantity"]
        conn.execute(
            "UPDATE partner_orgs SET current_intake_units = ? WHERE id = ?",
            (new_intake, partner_org_id),
        )
    log_activity(
        "agent", "route_donation_to_partner",
        f"Offer #{offer_id} ({offer['quantity']} {offer['unit']} {offer['item_name']}) -> {partner['name']}",
    )
    remaining = partner["weekly_capacity_units"] - new_intake
    return (
        f"Routed {offer['quantity']} {offer['unit']} of {offer['item_name']} from {offer['donor_name']} "
        f"to {partner['name']}. Their remaining weekly capacity is now {remaining:g} units."
    )
