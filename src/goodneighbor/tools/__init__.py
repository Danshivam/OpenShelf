from .inventory_tools import get_inventory_status, record_donation_intake, adjust_inventory
from .volunteer_tools import (
    get_shift_coverage,
    find_available_backup_volunteers,
    assign_volunteer_to_shift,
    notify_volunteer,
)
from .donation_tools import (
    list_open_donation_offers,
    get_partner_orgs,
    route_donation_to_partner,
)
from .ops_tools import escalate_to_human, get_current_datetime, notify_coordinator

ALL_TOOLS = [
    get_inventory_status,
    record_donation_intake,
    adjust_inventory,
    get_shift_coverage,
    find_available_backup_volunteers,
    assign_volunteer_to_shift,
    notify_volunteer,
    list_open_donation_offers,
    get_partner_orgs,
    route_donation_to_partner,
    escalate_to_human,
    get_current_datetime,
    notify_coordinator,
]
