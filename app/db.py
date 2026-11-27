"""SQLite storage: connection helper and schema."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL
);

-- One row per partner agency from the Shopify directory.
CREATE TABLE IF NOT EXISTS agencies (
    id INTEGER PRIMARY KEY,
    handle TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    partner_id TEXT, profile_url TEXT, tier TEXT, location TEXT, team_size TEXT,
    partner_since TEXT, website TEXT, linkedin TEXT,
    in_directory INTEGER NOT NULL DEFAULT 1,
    -- result of the most recent check
    status TEXT, final_url TEXT, careers_url TEXT, discovery_method TEXT, ats TEXT, ats_board TEXT,
    careers_email TEXT, careers_hash TEXT, notes TEXT, used_browser INTEGER DEFAULT 0,
    last_checked_at TEXT, last_success_at TEXT, last_run_id INTEGER,
    -- manual review of "careers page found but roles unclear"
    review_state TEXT,            -- NULL | no_openings | roles_added | ignored
    review_hash TEXT,             -- careers_hash when reviewed; a change re-opens the review
    reviewed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at TEXT,
    created_at TEXT NOT NULL
);

-- Roles keep their identity across runs (see app/reconcile.py).
CREATE TABLE IF NOT EXISTS roles (
    id INTEGER PRIMARY KEY,
    agency_id INTEGER NOT NULL REFERENCES agencies(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT, department TEXT, url TEXT, source TEXT, confidence TEXT,
    category TEXT, work_mode TEXT,
    state TEXT NOT NULL DEFAULT 'open',   -- open | missing | closed
    missing_count INTEGER NOT NULL DEFAULT 0,
    first_seen_run INTEGER, first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL, closed_at TEXT, updated_at TEXT,
    manual INTEGER NOT NULL DEFAULT 0,
    added_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    needs_recheck INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS roles_agency_key ON roles(agency_id, key);  -- same job URL may sit under two directory listings
CREATE INDEX IF NOT EXISTS roles_state ON roles(state);

CREATE TABLE IF NOT EXISTS role_events (
    id INTEGER PRIMARY KEY,
    role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    agency_id INTEGER NOT NULL,
    run_id INTEGER,
    type TEXT NOT NULL,           -- added | updated | reposted | missing | removed | reopened
    detail TEXT,
    at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_run ON role_events(run_id);
CREATE INDEX IF NOT EXISTS events_agency ON role_events(agency_id);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    trigger TEXT NOT NULL,        -- schedule | manual
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    status TEXT NOT NULL,         -- running | retrying | completed | failed | stopped
    baseline INTEGER NOT NULL DEFAULT 0,  -- first ever run: roles are not flagged "new"
    started_at TEXT NOT NULL, finished_at TEXT,
    total INTEGER DEFAULT 0, processed INTEGER DEFAULT 0,
    hiring INTEGER DEFAULT 0, roles_found INTEGER DEFAULT 0,
    new_roles INTEGER DEFAULT 0, removed_roles INTEGER DEFAULT 0, rate_limited INTEGER DEFAULT 0,
    status_counts TEXT, settings TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS run_agencies (
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    agency_id INTEGER NOT NULL REFERENCES agencies(id) ON DELETE CASCADE,
    status TEXT NOT NULL, role_count INTEGER NOT NULL DEFAULT 0, notes TEXT, at TEXT NOT NULL,
    PRIMARY KEY (run_id, agency_id)
);
CREATE TABLE IF NOT EXISTS run_logs (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    at TEXT NOT NULL, status TEXT, line TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_roles (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    status TEXT,                  -- saved | applied | not_interested | NULL
    note TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, role_id)
);
CREATE TABLE IF NOT EXISTS watches (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    agency_id INTEGER NOT NULL REFERENCES agencies(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, agency_id)
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    agency_id INTEGER REFERENCES agencies(id) ON DELETE CASCADE,
    run_id INTEGER,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    read_at TEXT,
    emailed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS schedule (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    enabled INTEGER NOT NULL DEFAULT 0,
    mode TEXT NOT NULL DEFAULT 'daily',   -- interval | daily | weekly | cron
    interval_hours INTEGER NOT NULL DEFAULT 6,
    time TEXT NOT NULL DEFAULT '06:00',
    timezone TEXT NOT NULL DEFAULT 'UTC',
    days TEXT NOT NULL DEFAULT 'mon,tue,wed,thu,fri,sat,sun',
    cron TEXT NOT NULL DEFAULT '0 6 * * *',
    service TEXT NOT NULL DEFAULT 'store_building',
    location TEXT NOT NULL DEFAULT 'US',
    use_browser INTEGER NOT NULL DEFAULT 1,
    retry_rate_limited INTEGER NOT NULL DEFAULT 1,
    email_team INTEGER NOT NULL DEFAULT 0,
    skip_if_running INTEGER NOT NULL DEFAULT 1,
    concurrency INTEGER NOT NULL DEFAULT 8,
    last_fired_at TEXT
);
INSERT OR IGNORE INTO schedule (id) VALUES (1);
"""

_lock = threading.Lock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path or settings.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")      # readers don't block the scraper's writes
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init(path: Path | None = None) -> None:
    with connect(path) as conn:
        conn.executescript(SCHEMA)


@contextmanager
def tx(conn: sqlite3.Connection):
    """Serialised write transaction (one writer at a time across threads)."""
    with _lock:
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise


def rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


def one(cur) -> dict | None:
    r = cur.fetchone()
    return dict(r) if r else None
