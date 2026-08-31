"""
Populate the datastore with a realistic one-week scenario for
Riverside Community Food Bank, anchored to *today* so every demo run
produces live, meaningful coverage/expiry windows.

Scenario is built so that:
- Two shifts fill cleanly from the backup pool (autonomous).
- One shift stays short even after backups are contacted (escalation).
- One inventory item is expiring soon with a clean redistribution match (autonomous).
- One donation offer is a clean single-match (autonomous).
- One donation offer is genuinely ambiguous: two partner orgs are both
  high-need and close in remaining capacity (escalation).
"""

from datetime import date, timedelta

from .db import get_conn, reset_db, log_activity


def _d(days_from_today: int) -> str:
    return (date.today() + timedelta(days=days_from_today)).isoformat()


def seed() -> None:
    reset_db()
    with get_conn() as conn:
        # --- Volunteers ---------------------------------------------------
        volunteers = [
            ("Maya Chen", "555-0101", "maya@example.org", "driving,checkin", 0.95, 0, 1),
            ("Devon Lee", "555-0102", "devon@example.org", "heavy_lifting", 0.9, 0, 1),
            ("Priya Nair", "555-0103", "priya@example.org", "checkin", 0.85, 0, 1),
            ("Sam Okafor", "555-0104", "sam@example.org", "driving", 0.7, 0, 1),
            # backup / on-call pool
            ("Jordan Ruiz", "555-0201", "jordan@example.org", "checkin,driving", 0.88, 1, 1),
            ("Ana Torres", "555-0202", "ana@example.org", "heavy_lifting", 0.8, 1, 1),
            ("Ben Whitfield", "555-0203", "ben@example.org", "checkin", 0.6, 1, 1),
        ]
        conn.executemany(
            "INSERT INTO volunteers (name, phone, email, skills, reliability_score, is_backup, active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            volunteers,
        )

        # --- Shifts (next 7 days) -----------------------------------------
        # (role, days_from_today, start, end, location, needed_count)
        shifts = [
            ("Distribution line", 1, "09:00", "13:00", "Main warehouse", 3),
            ("Distribution line", 2, "09:00", "13:00", "Main warehouse", 2),
            ("Truck pickup", 6, "07:00", "10:00", "Depot", 2),  # will end up short -> escalation
            ("Intake sorting", 3, "14:00", "17:00", "Main warehouse", 2),
        ]
        conn.executemany(
            "INSERT INTO shifts (role, shift_date, start_time, end_time, location, needed_count) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(r, _d(dd), s, e, loc, n) for (r, dd, s, e, loc, n) in shifts],
        )

        # Confirmed assignments: shift 1 fully staffed by regulars,
        # shift 2 short by one (fillable from backups),
        # shift 3 (truck pickup) short by two with only one usable backup -> escalation,
        # shift 4 fully staffed.
        vol_ids = {name: i + 1 for i, name in enumerate([v[0] for v in volunteers])}
        assignments = [
            (1, vol_ids["Maya Chen"], "confirmed"),
            (1, vol_ids["Devon Lee"], "confirmed"),
            (1, vol_ids["Priya Nair"], "confirmed"),
            (2, vol_ids["Sam Okafor"], "confirmed"),  # needs 2, has 1 -> fillable from backup
            (4, vol_ids["Maya Chen"], "confirmed"),
            (4, vol_ids["Devon Lee"], "confirmed"),
            # Truck pickup (shift 3) intentionally left with 0 assignments and
            # requires "driving" skill; only Jordan (backup) has it, Ana/Ben don't
            # drive, so after contacting backups it's still short by one -> escalation.
        ]
        conn.executemany(
            "INSERT INTO shift_assignments (shift_id, volunteer_id, status) VALUES (?, ?, ?)",
            assignments,
        )

        # --- Inventory ------------------------------------------------------
        inventory = [
            ("Canned vegetables", "shelf_stable", 340, "cans", None, 100, 0, 1.2),
            ("Fresh strawberries", "produce", 60, "lbs", _d(2), 20, 1, 2.5),   # expiring soon, clean match
            ("Whole milk", "dairy", 30, "gallons", _d(1), 40, 1, 3.8),          # below threshold AND expiring
            ("Rice (bulk)", "shelf_stable", 25, "lbs", None, 50, 0, 0.9),       # low stock, non-perishable -> just flag
            ("Peanut butter", "shelf_stable", 120, "jars", None, 40, 0, 2.1),
        ]
        conn.executemany(
            "INSERT INTO inventory (item_name, category, quantity, unit, expiry_date, "
            "min_threshold, perishable, est_unit_value_usd) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            inventory,
        )

        # --- Partner orgs -----------------------------------------------
        partners = [
            ("Elmwood Shelter", "shelter", "produce,dairy,prepared_food", 200, 40, "elmwood@example.org", 4.2, 1),
            ("Riverside Community Fridge", "mutual_aid", "produce,shelf_stable", 80, 10, "fridge@example.org", 1.1, 0),
            ("Maple Street School Pantry", "school", "shelf_stable,dairy", 150, 30, "maple@example.org", 6.0, 1),
        ]
        conn.executemany(
            "INSERT INTO partner_orgs (name, org_type, accepts_categories, weekly_capacity_units, "
            "current_intake_units, contact, distance_km, high_need) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            partners,
        )

        # --- Donation offers -----------------------------------------------
        offers = [
            # Clean match: only the Community Fridge accepts produce with
            # plenty of headroom and no other high-need contender close behind.
            ("Local Farms Co-op", "Bell peppers", "produce", 40, "lbs", 1,
             "Good condition, harvested yesterday", "Tomorrow 8-10am", "open", None),
            # Ambiguous: dairy accepted by BOTH Elmwood (high-need) and Maple
            # Street (high-need), both with similar remaining capacity -> escalate.
            ("Sunridge Dairy", "Yogurt cups", "dairy", 180, "units", 1,
             "Best-by in 5 days, needs refrigerated pickup", "Today 3-6pm", "open", None),
        ]
        conn.executemany(
            "INSERT INTO donation_offers (donor_name, item_name, category, quantity, unit, "
            "perishable, condition_notes, pickup_window, status, routed_to_partner_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            offers,
        )

    log_activity("system", "seed", "Seeded demo scenario for Riverside Community Food Bank", autonomous=False)


if __name__ == "__main__":
    seed()
    print("Seeded demo database.")
