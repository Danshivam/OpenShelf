"""
Deterministic (non-LLM) implementations of the three background cycles.

These encode ONE correct path through the autonomy policy in `config.py`,
calling the exact same tools the real `strands.Agent` uses (see `agent.py`).
They exist for two reasons:

1. Anyone can verify the tool layer and policy actually work without AWS
   credentials or Bedrock access (see demo/scripted_walkthrough.py).
2. The dashboard can offer a "run cycle now" button that works out of the
   box; if Bedrock credentials ARE configured, the dashboard prefers
   invoking the real agent (goodneighbor.orchestrator.run_cycle) and only
   falls back to this deterministic path otherwise — see dashboard/server.py.

In production (AgentCore), the real LLM-driven agent is what runs on the
EventBridge schedule, not this module.
"""

from .tools.volunteer_tools import (
    get_shift_coverage,
    find_available_backup_volunteers,
    notify_volunteer,
    assign_volunteer_to_shift,
)
from .tools.inventory_tools import get_inventory_status, adjust_inventory
from .tools.donation_tools import (
    list_open_donation_offers,
    get_partner_orgs,
    route_donation_to_partner,
)
from .tools.ops_tools import escalate_to_human, notify_coordinator
from .config import (
    AUTONOMOUS_ROUTING_VALUE_CEILING_USD,
    LARGE_DONATION_UNIT_THRESHOLD,
    MATCH_CONFIDENCE_MARGIN,
)


def _entry(kind, text):
    return {"kind": kind, "text": text}


def run_volunteer_cycle() -> list:
    log = []
    coverage = get_shift_coverage()
    for shift in coverage:
        if shift["gap"] <= 0:
            log.append(_entry("info", f"{shift['role']} on {shift['shift_date']}: fully covered."))
            continue

        log.append(_entry(
            "info",
            f"{shift['role']} on {shift['shift_date']}: short {shift['gap']} of {shift['needed_count']}.",
        ))
        required_skill = "driving" if shift["role"] == "Truck pickup" else ""
        candidates = find_available_backup_volunteers(shift["id"], required_skill=required_skill)
        filled = 0
        for candidate in candidates:
            if filled >= shift["gap"]:
                break
            log.append(_entry("action", notify_volunteer(
                candidate["id"], f"Can you cover {shift['role']} on {shift['shift_date']}?"
            )))
            log.append(_entry("action", assign_volunteer_to_shift(shift["id"], candidate["id"])))
            filled += 1

        remaining_gap = shift["gap"] - filled
        if remaining_gap > 0:
            attempt_note = (
                "No qualified backup volunteers were available to contact."
                if not candidates else f"Contacted {len(candidates)} qualified backup(s), filled {filled}."
            )
            escalate_to_human(
                title=f"{shift['role']} on {shift['shift_date']} still short {remaining_gap}",
                description=(
                    f"Checked the backup pool for shift #{shift['id']} "
                    f"({shift['role']}, {shift['start_time']}-{shift['end_time']}). "
                    f"{attempt_note} Coverage is still short {remaining_gap}."
                ),
                category="coverage",
                options=[
                    "Approve overtime pay to recruit an outside volunteer",
                    "Reduce scope of the shift to what current staffing can handle",
                    "Cancel/reschedule the shift",
                ],
                urgency="high",
            )
            log.append(_entry("escalation", f"Escalated: {shift['role']} on {shift['shift_date']} still short {remaining_gap}."))
    return log


def run_inventory_cycle() -> list:
    log = []
    status = get_inventory_status()
    for item in status["low_stock"]:
        if item["perishable"]:
            continue
        notify_coordinator(
            f"Low stock: {item['item_name']} at {item['quantity']:g} {item['unit']} "
            f"(below threshold {item['min_threshold']:g}). Consider a reorder."
        )
        log.append(_entry("info", f"Flagged low stock: {item['item_name']} ({item['quantity']:g} {item['unit']})."))

    for item in status["expiring_soon"]:
        est_value = item["quantity"] * item["est_unit_value_usd"]
        log.append(_entry(
            "info",
            f"{item['item_name']}: {item['quantity']:g} {item['unit']} expiring {item['expiry_date']} (~${est_value:,.2f})",
        ))
        partners = get_partner_orgs(category=item["category"])
        eligible = [p for p in partners if p["remaining_capacity"] >= item["quantity"]]

        if est_value >= AUTONOMOUS_ROUTING_VALUE_CEILING_USD:
            escalate_to_human(
                title=f"{item['item_name']} expiring soon — value above auto-routing ceiling",
                description=(
                    f"{item['quantity']:g} {item['unit']} of {item['item_name']} expires "
                    f"{item['expiry_date']}, estimated value ~${est_value:,.2f}, above the "
                    f"${AUTONOMOUS_ROUTING_VALUE_CEILING_USD} autonomous ceiling."
                ),
                category="inventory",
                options=[f"Approve routing to {p['name']}" for p in eligible] or ["No partner has capacity — advise"],
                urgency="high",
            )
            log.append(_entry("escalation", f"Escalated: {item['item_name']} above auto-routing value ceiling."))
        elif len(eligible) == 1:
            partner = eligible[0]
            log.append(_entry("action", adjust_inventory(
                item["item_name"], -item["quantity"], f"Routed to {partner['name']} before expiry"
            )))
            notify_coordinator(
                f"Routed {item['quantity']:g} {item['unit']} of {item['item_name']} to {partner['name']} "
                f"before it expired ({item['expiry_date']})."
            )
        else:
            escalate_to_human(
                title=f"No single clean recipient for expiring {item['item_name']}",
                description=(
                    f"{item['quantity']:g} {item['unit']} of {item['item_name']} expires "
                    f"{item['expiry_date']}. {len(eligible)} partner(s) could take it "
                    f"({', '.join(p['name'] for p in eligible) or 'none'})."
                ),
                category="inventory",
                options=[f"Route to {p['name']}" for p in eligible] or ["No eligible partner — advise"],
                urgency="normal",
            )
            log.append(_entry("escalation", f"Escalated: no single clean recipient for {item['item_name']}."))
    return log


def _donation_options(offer, partners=None):
    if partners is None:
        partners = get_partner_orgs(category=offer["category"])
    opts = [f"Route to {p['name']}" for p in partners]
    opts.append("Split between the listed partners")
    return opts


def run_donation_cycle() -> list:
    log = []
    offers = list_open_donation_offers()
    for offer in offers:
        log.append(_entry(
            "info",
            f"Offer #{offer['id']}: {offer['quantity']:g} {offer['unit']} {offer['item_name']} "
            f"from {offer['donor_name']} ({offer['category']})",
        ))

        if offer["quantity"] >= LARGE_DONATION_UNIT_THRESHOLD:
            escalate_to_human(
                title=f"Large donation offer: {offer['quantity']:g} {offer['unit']} {offer['item_name']}",
                description=(
                    f"{offer['donor_name']} is offering {offer['quantity']:g} {offer['unit']} of "
                    f"{offer['item_name']} ({offer['category']}), pickup window {offer['pickup_window']}. "
                    f"This is at/above the {LARGE_DONATION_UNIT_THRESHOLD}-unit threshold that always "
                    f"gets a human look, regardless of match quality."
                ),
                category="donation",
                options=_donation_options(offer),
                urgency="high" if offer["perishable"] else "normal",
            )
            log.append(_entry("escalation", f"Escalated: {offer['item_name']} offer is oversized."))
            continue

        partners = get_partner_orgs(category=offer["category"])
        eligible = sorted(
            [p for p in partners if p["remaining_capacity"] >= offer["quantity"]],
            key=lambda p: -p["remaining_capacity"],
        )

        if not eligible:
            escalate_to_human(
                title=f"No partner has capacity for {offer['item_name']}",
                description=f"{offer['donor_name']}'s offer of {offer['item_name']} has no eligible partner "
                             f"with remaining capacity.",
                category="donation",
                options=["Decline the offer", "Ask a partner to make an exception this week"],
                urgency="normal",
            )
            log.append(_entry("escalation", f"Escalated: no partner has capacity for {offer['item_name']}."))
            continue

        if len(eligible) == 1:
            log.append(_entry("action", route_donation_to_partner(offer["id"], eligible[0]["id"])))
            continue

        top, runner_up = eligible[0], eligible[1]
        margin = (top["remaining_capacity"] - runner_up["remaining_capacity"]) / max(top["remaining_capacity"], 1)
        if margin >= MATCH_CONFIDENCE_MARGIN and not (top["high_need"] and runner_up["high_need"]):
            log.append(_entry("action", route_donation_to_partner(offer["id"], top["id"])))
        else:
            escalate_to_human(
                title=f"Two comparable recipients for {offer['item_name']}",
                description=(
                    f"{top['name']} and {runner_up['name']} both accept {offer['category']} and both have "
                    f"comparable remaining capacity ({top['remaining_capacity']:g} vs "
                    f"{runner_up['remaining_capacity']:g} units); "
                    f"{'both are flagged high-need. ' if top['high_need'] and runner_up['high_need'] else ''}"
                    f"Not a clean autonomous call."
                ),
                category="donation",
                options=_donation_options(offer, [top, runner_up]),
                urgency="high" if offer["perishable"] else "normal",
            )
            log.append(_entry("escalation", f"Escalated: two comparable recipients for {offer['item_name']}."))
    return log


CYCLE_FUNCS = {
    "volunteers": run_volunteer_cycle,
    "inventory": run_inventory_cycle,
    "donations": run_donation_cycle,
}
