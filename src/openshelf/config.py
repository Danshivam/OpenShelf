"""
Configuration and the *autonomy contract*.

Every threshold in this file is a policy decision: how far the agent is
trusted to act on its own before a human has to be looped in. Keeping these
in one place makes the org's risk tolerance auditable and easy to change
without touching agent logic.
"""

import os

# --- Identity -----------------------------------------------------------

ORG_NAME = os.environ.get("GNA_ORG_NAME", "Riverside Community Food Bank")
DB_PATH = os.environ.get("GNA_DB_PATH", os.path.join(os.path.dirname(__file__), "..", "..", "goodneighbor.db"))

# --- Model ----------------------------------------------------------------

# Any Bedrock-hosted model id the deploying org has access to.
MODEL_PROVIDER = os.environ.get("GNA_MODEL_PROVIDER", "bedrock-mantle")  # "bedrock" | "bedrock-mantle"
BEDROCK_MODEL_ID = os.environ.get("GNA_MODEL_ID", "google.gemma-4-31b")
BEDROCK_REGION = os.environ.get("AWS_REGION", "us-east-1")

# --- Autonomy policy: volunteer coverage ----------------------------------

# How far ahead the agent looks for shifts that need coverage.
COVERAGE_LOOKAHEAD_DAYS = 7

# If a shift is still short-staffed once it's inside this window, escalate
# instead of continuing to try backups silently.
COVERAGE_ESCALATION_WINDOW_HOURS = 36

# Never message the same backup volunteer more than this many times for one
# shift gap in a single cycle (avoid spamming).
MAX_BACKUP_CONTACTS_PER_SHIFT = 3

# --- Autonomy policy: inventory & expiry ----------------------------------

# Items expiring within this many days are flagged for redistribution.
EXPIRY_WARNING_DAYS = 3

# The agent may autonomously route a redistribution if the retail value is
# under this amount; above it, a human confirms (large donations are also a
# tax-receipt / relationship matter, not just logistics).
AUTONOMOUS_ROUTING_VALUE_CEILING_USD = 250

# --- Autonomy policy: donation intake --------------------------------------

# The agent may auto-confirm a donation match only when exactly one partner
# org has both remaining capacity AND matches the category with no other
# org within this competitiveness margin (0-1, share of remaining capacity).
MATCH_CONFIDENCE_MARGIN = 0.25

# Any donation offer at or above this quantity always gets a human glance,
# regardless of how clean the match looks (large intakes affect logistics,
# storage, and relationships with multiple partners at once).
LARGE_DONATION_UNIT_THRESHOLD = 150

# Categories that always escalate on intake because a wrong call is a safety
# issue, not just a logistics one.
ALWAYS_ESCALATE_CATEGORIES = {"prepared_food", "infant_formula", "recalled_or_unknown"}
