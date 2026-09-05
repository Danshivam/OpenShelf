"""
SQLite datastore for OpenShelf.

Deliberately plain stdlib sqlite3 — this is a single small org's operational
data, not a system that needs a managed database. Swap for RDS/Aurora behind
the same helper functions if a deployment ever needs multi-instance access.
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS volunteers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT,
    email TEXT,
    skills TEXT,                    -- comma separated tags e.g. "driving,heavy_lifting"
    reliability_score REAL DEFAULT 0.8,  -- 0-1, historical show-up rate
    is_backup INTEGER DEFAULT 0,    -- 1 = on the backup/on-call pool
    active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS shifts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    shift_date TEXT NOT NULL,       -- ISO date
    start_time TEXT NOT NULL,       -- HH:MM
    end_time TEXT NOT NULL,
    location TEXT,
    needed_count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS shift_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shift_id INTEGER NOT NULL REFERENCES shifts(id),
    volunteer_id INTEGER NOT NULL REFERENCES volunteers(id),
    status TEXT NOT NULL DEFAULT 'confirmed',  -- confirmed | pending | declined
    assigned_by TEXT DEFAULT 'agent',
    assigned_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_name TEXT NOT NULL,
    category TEXT NOT NULL,
    quantity REAL NOT NULL,
    unit TEXT NOT NULL,
    expiry_date TEXT,               -- ISO date, nullable for non-perishables
    min_threshold REAL NOT NULL DEFAULT 0,
    perishable INTEGER DEFAULT 0,
    est_unit_value_usd REAL DEFAULT 1.0
);

CREATE TABLE IF NOT EXISTS partner_orgs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    org_type TEXT,                  -- shelter, pantry, school, etc.
    accepts_categories TEXT,        -- comma separated
    weekly_capacity_units REAL NOT NULL,
    current_intake_units REAL NOT NULL DEFAULT 0,
    contact TEXT,
    distance_km REAL DEFAULT 0,
    high_need INTEGER DEFAULT 0     -- 1 if currently flagged as high-need
);

CREATE TABLE IF NOT EXISTS donation_offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    donor_name TEXT NOT NULL,
    item_name TEXT NOT NULL,
    category TEXT NOT NULL,
    quantity REAL NOT NULL,
    unit TEXT NOT NULL,
    perishable INTEGER DEFAULT 0,
    condition_notes TEXT,
    offered_at TEXT DEFAULT (datetime('now')),
    pickup_window TEXT,
    status TEXT NOT NULL DEFAULT 'open',  -- open | routed | escalated | declined
    routed_to_partner_id INTEGER REFERENCES partner_orgs(id)
);

CREATE TABLE IF NOT EXISTS escalations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT DEFAULT (datetime('now')),
    category TEXT NOT NULL,          -- coverage | inventory | donation
    reference_key TEXT,              -- stable id for the underlying situation
                                      -- (e.g. "shift-3", "donation-offer-2",
                                      -- "inventory-Whole milk") used to avoid
                                      -- re-escalating the same thing every cycle
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    options_json TEXT,               -- JSON list of {"label": ..., "detail": ...}
    urgency TEXT DEFAULT 'normal',   -- low | normal | high
    status TEXT DEFAULT 'pending',   -- pending | resolved | dismissed
    resolved_at TEXT,
    resolution TEXT
);

CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT DEFAULT (datetime('now')),
    actor TEXT NOT NULL,              -- 'agent' or a human name
    action TEXT NOT NULL,
    detail TEXT,
    autonomous INTEGER DEFAULT 1      -- 1 = agent acted without asking
);
"""


def _resolved_path() -> str:
    return os.path.abspath(DB_PATH)


@contextmanager
def get_conn():
    conn = sqlite3.connect(_resolved_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> str:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
    return _resolved_path()


def reset_db() -> str:
    path = _resolved_path()
    if os.path.exists(path):
        os.remove(path)
    return init_db()


def log_activity(actor: str, action: str, detail: str = "", autonomous: bool = True) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO activity_log (timestamp, actor, action, detail, autonomous) "
            "VALUES (?, ?, ?, ?, ?)",
            (datetime.utcnow().isoformat(timespec="seconds"), actor, action, detail, int(autonomous)),
        )
        return cur.lastrowid


def rows_to_dicts(rows) -> list:
    return [dict(r) for r in rows]
