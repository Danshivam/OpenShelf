"""Inventory monitoring and intake-recording tools."""

from datetime import date, timedelta

from strands import tool

from ..db import get_conn, log_activity, rows_to_dicts
from ..config import EXPIRY_WARNING_DAYS


@tool
def get_inventory_status() -> dict:
    """Get current inventory levels, flagging items below their minimum
    threshold and perishable items expiring within the policy warning
    window. Always check this before deciding whether anything needs
    redistribution or a reorder note.

    Returns:
        A dict with "low_stock" and "expiring_soon" lists, each item
        including id, item_name, category, quantity, unit, expiry_date,
        min_threshold, perishable, and est_unit_value_usd.
    """
    warning_date = (date.today() + timedelta(days=EXPIRY_WARNING_DAYS)).isoformat()
    with get_conn() as conn:
        low_stock = conn.execute(
            "SELECT * FROM inventory WHERE quantity < min_threshold ORDER BY quantity ASC"
        ).fetchall()
        expiring_soon = conn.execute(
            "SELECT * FROM inventory WHERE perishable = 1 AND expiry_date IS NOT NULL "
            "AND expiry_date <= ? ORDER BY expiry_date ASC",
            (warning_date,),
        ).fetchall()
    return {
        "low_stock": rows_to_dicts(low_stock),
        "expiring_soon": rows_to_dicts(expiring_soon),
        "expiry_warning_window_days": EXPIRY_WARNING_DAYS,
    }


@tool
def adjust_inventory(item_name: str, quantity_delta: float, reason: str) -> str:
    """Adjust the on-hand quantity of an inventory item (e.g. after routing
    part of a perishable batch to a partner org, or logging a reorder
    received). Use a negative delta to remove stock, positive to add.

    Args:
        item_name: Exact inventory item name (see get_inventory_status).
        quantity_delta: Amount to add (positive) or remove (negative).
        reason: Why the adjustment is happening, for the audit log.

    Returns:
        Confirmation with the new quantity, or an error if the item isn't found.
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, quantity, unit FROM inventory WHERE item_name = ?", (item_name,)
        ).fetchone()
        if not row:
            return f"No inventory item named '{item_name}' found."
        new_qty = row["quantity"] + quantity_delta
        conn.execute("UPDATE inventory SET quantity = ? WHERE id = ?", (new_qty, row["id"]))
    log_activity("agent", "adjust_inventory", f"{item_name}: {quantity_delta:+g} ({reason})")
    return f"{item_name} adjusted by {quantity_delta:+g} {row['unit']}. New quantity: {new_qty:g} {row['unit']}."


@tool
def record_donation_intake(
    donor_name: str,
    item_name: str,
    category: str,
    quantity: float,
    unit: str,
    perishable: bool,
    condition_notes: str = "",
    pickup_window: str = "",
) -> dict:
    """Record a new incoming donation offer so it can be evaluated for routing.

    Args:
        donor_name: Who is offering the donation.
        item_name: What's being offered.
        category: One of "produce", "dairy", "shelf_stable", "prepared_food",
            "infant_formula", or "recalled_or_unknown".
        quantity: Amount offered.
        unit: Unit of quantity (e.g. "lbs", "units", "cases").
        perishable: Whether the item needs prompt handling.
        condition_notes: Any notes on freshness/condition/allergens.
        pickup_window: When the donor can have it picked up.

    Returns:
        The created donation offer record, including its id.
    """
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO donation_offers (donor_name, item_name, category, quantity, unit, "
            "perishable, condition_notes, pickup_window, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open')",
            (donor_name, item_name, category, quantity, unit, int(perishable), condition_notes, pickup_window),
        )
        offer_id = cur.lastrowid
    log_activity(
        "agent", "record_donation_intake",
        f"#{offer_id} {donor_name}: {quantity} {unit} {item_name} ({category})",
    )
    return {
        "id": offer_id,
        "donor_name": donor_name,
        "item_name": item_name,
        "category": category,
        "quantity": quantity,
        "unit": unit,
        "perishable": perishable,
        "status": "open",
    }
