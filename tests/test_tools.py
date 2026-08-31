"""
Unit tests for the tool layer — the part of the system that doesn't need an
LLM or AWS credentials to verify. Run with: pytest tests/
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from goodneighbor import config


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setattr(config, "DB_PATH", str(db_file))
    # db.py imports DB_PATH at module load time, so patch it there too.
    import goodneighbor.db as db_module

    monkeypatch.setattr(db_module, "DB_PATH", str(db_file))
    from goodneighbor.seed_data import seed

    seed()
    yield db_file


def test_seed_creates_expected_counts(fresh_db):
    from goodneighbor.db import get_conn

    with get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) c FROM volunteers").fetchone()["c"] == 7
        assert conn.execute("SELECT COUNT(*) c FROM shifts").fetchone()["c"] == 4
        assert conn.execute("SELECT COUNT(*) c FROM donation_offers").fetchone()["c"] == 2


def test_shift_coverage_reports_gap(fresh_db):
    from goodneighbor.tools.volunteer_tools import get_shift_coverage

    coverage = get_shift_coverage()
    by_role = {(c["role"], c["shift_date"]): c for c in coverage}
    truck = [c for c in coverage if c["role"] == "Truck pickup"][0]
    assert truck["confirmed_count"] == 0
    assert truck["gap"] == truck["needed_count"]


def test_backup_search_respects_skill_filter(fresh_db):
    from goodneighbor.tools.volunteer_tools import get_shift_coverage, find_available_backup_volunteers

    truck_shift = [s for s in get_shift_coverage() if s["role"] == "Truck pickup"][0]
    drivers = find_available_backup_volunteers(truck_shift["id"], required_skill="driving")
    assert all("driving" in (c["skills"] or "") for c in drivers)
    # Only Jordan Ruiz has driving in the backup pool per seed data.
    assert {c["name"] for c in drivers} == {"Jordan Ruiz"}


def test_assign_volunteer_updates_coverage(fresh_db):
    from goodneighbor.tools.volunteer_tools import (
        get_shift_coverage,
        find_available_backup_volunteers,
        assign_volunteer_to_shift,
    )

    shift = [s for s in get_shift_coverage() if s["role"] == "Distribution line" and s["gap"] > 0][0]
    candidate = find_available_backup_volunteers(shift["id"])[0]
    assign_volunteer_to_shift(shift["id"], candidate["id"])
    updated = [s for s in get_shift_coverage() if s["id"] == shift["id"]][0]
    assert updated["gap"] == shift["gap"] - 1


def test_inventory_flags_expiring_and_low_stock(fresh_db):
    from goodneighbor.tools.inventory_tools import get_inventory_status

    status = get_inventory_status()
    expiring_names = {i["item_name"] for i in status["expiring_soon"]}
    assert "Fresh strawberries" in expiring_names
    assert "Whole milk" in expiring_names
    low_stock_names = {i["item_name"] for i in status["low_stock"]}
    assert "Whole milk" in low_stock_names or "Rice (bulk)" in low_stock_names


def test_adjust_inventory_changes_quantity(fresh_db):
    from goodneighbor.tools.inventory_tools import adjust_inventory, get_inventory_status

    before = [i for i in get_inventory_status()["expiring_soon"] if i["item_name"] == "Fresh strawberries"][0]
    adjust_inventory("Fresh strawberries", -20, "test routing")
    after = [i for i in get_inventory_status()["expiring_soon"] if i["item_name"] == "Fresh strawberries"][0]
    assert after["quantity"] == before["quantity"] - 20


def test_clean_donation_match_has_one_clear_best_partner(fresh_db):
    """Two partners both accept produce and have room, but only one is
    NOT flagged high-need and it holds a clear capacity lead — a clean
    autonomous call per the policy's margin/high-need rule."""
    from goodneighbor.tools.donation_tools import list_open_donation_offers, get_partner_orgs, route_donation_to_partner
    from goodneighbor.config import MATCH_CONFIDENCE_MARGIN

    offer = [o for o in list_open_donation_offers() if o["item_name"] == "Bell peppers"][0]
    partners = get_partner_orgs(category="produce")
    eligible = sorted(
        [p for p in partners if p["remaining_capacity"] >= offer["quantity"]],
        key=lambda p: -p["remaining_capacity"],
    )
    assert len(eligible) == 2
    top, runner_up = eligible[0], eligible[1]
    margin = (top["remaining_capacity"] - runner_up["remaining_capacity"]) / top["remaining_capacity"]
    assert margin >= MATCH_CONFIDENCE_MARGIN
    assert not (top["high_need"] and runner_up["high_need"])  # not a genuine conflict

    result = route_donation_to_partner(offer["id"], top["id"])
    assert "Routed" in result


def test_large_donation_exceeds_capacity_of_either_partner(fresh_db):
    """The yogurt offer is both oversized (triggers the always-escalate
    threshold) and, independently, larger than any single partner's
    remaining capacity — reinforcing that this is not a clean auto-route."""
    from goodneighbor.tools.donation_tools import list_open_donation_offers, get_partner_orgs
    from goodneighbor.config import LARGE_DONATION_UNIT_THRESHOLD

    offer = [o for o in list_open_donation_offers() if o["item_name"] == "Yogurt cups"][0]
    assert offer["quantity"] >= LARGE_DONATION_UNIT_THRESHOLD

    partners = get_partner_orgs(category="dairy")
    assert len(partners) >= 2
    assert all(p["remaining_capacity"] < offer["quantity"] for p in partners)


def test_escalation_lifecycle(fresh_db):
    from goodneighbor.tools.ops_tools import escalate_to_human
    from goodneighbor.escalation import list_pending_escalations, resolve_escalation

    escalate_to_human(
        title="Test escalation",
        description="Just a test.",
        category="donation",
        options=["Option A", "Option B"],
        urgency="low",
    )
    pending = list_pending_escalations()
    assert len(pending) == 1
    assert pending[0]["title"] == "Test escalation"

    resolve_escalation(pending[0]["id"], "Chose Option A")
    assert list_pending_escalations() == []


def test_digest_counts_autonomous_actions(fresh_db):
    from goodneighbor.tools.volunteer_tools import find_available_backup_volunteers, assign_volunteer_to_shift
    from goodneighbor.tools.volunteer_tools import get_shift_coverage
    from goodneighbor.digest import build_digest

    shift = [s for s in get_shift_coverage() if s["gap"] > 0 and s["role"] == "Distribution line"][0]
    candidate = find_available_backup_volunteers(shift["id"])[0]
    assign_volunteer_to_shift(shift["id"], candidate["id"])

    digest = build_digest()
    assert digest["total_autonomous_actions"] >= 1
    assert "assign_volunteer_to_shift" in digest["actions_by_type"]
