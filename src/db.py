"""SQLite schema and helpers. All queries are parameterized."""
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS emails (
    email_id      TEXT PRIMARY KEY,      -- content hash (dedup key)
    source_file   TEXT NOT NULL,         -- first maildir path seen
    message_id    TEXT,
    sender        TEXT,
    sender_name   TEXT,
    sent_at_utc   TEXT,                  -- ISO-8601 UTC, NULL if unparseable
    original_date TEXT,                  -- Date header as written
    date_valid    INTEGER NOT NULL,      -- 1 if year in 1998-2002
    weekday       INTEGER,               -- 0=Mon..6=Sun (US/Pacific header date)
    subject       TEXT,
    body_authored TEXT,                  -- sender's own text, boilerplate removed
    raw_email     TEXT NOT NULL,         -- original message, for evidence view
    mailbox       TEXT,
    folder        TEXT,
    n_recipients  INTEGER,
    n_copies      INTEGER DEFAULT 1,
    parse_status  TEXT
);
CREATE TABLE IF NOT EXISTS recipients (
    email_id       TEXT NOT NULL,
    recipient      TEXT NOT NULL,
    recipient_type TEXT NOT NULL,        -- to / cc / bcc (first seen wins)
    PRIMARY KEY (email_id, recipient)
);
CREATE TABLE IF NOT EXISTS source_occurrences (
    email_id    TEXT NOT NULL,
    source_file TEXT NOT NULL,
    mailbox     TEXT,
    folder      TEXT
);
CREATE TABLE IF NOT EXISTS risk_results (
    email_id      TEXT PRIMARY KEY,
    score         REAL NOT NULL,
    priority      TEXT NOT NULL,
    k_points      REAL, c_points REAL, t_points REAL,
    rules         TEXT,                  -- comma-separated rule ids
    reasons_json  TEXT NOT NULL,
    not_evaluated_json TEXT,
    rule_version  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS edges (
    sender TEXT, recipient TEXT, n_emails INTEGER, first_utc TEXT, last_utc TEXT,
    PRIMARY KEY (sender, recipient)
);
CREATE TABLE IF NOT EXISTS people (
    sender TEXT PRIMARY KEY, sender_name TEXT, n_sent INTEGER, n_flagged INTEGER,
    flag_rate_per_1000 REAL, max_score REAL, top_rule TEXT, eligible INTEGER
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

INDEXES = """
CREATE INDEX IF NOT EXISTS ix_emails_sender ON emails(sender);
CREATE INDEX IF NOT EXISTS ix_emails_sent ON emails(sent_at_utc);
CREATE INDEX IF NOT EXISTS ix_recip_recipient ON recipients(recipient);
CREATE INDEX IF NOT EXISTS ix_src_email ON source_occurrences(email_id);
CREATE INDEX IF NOT EXISTS ix_risk_score ON risk_results(score DESC);
"""


def connect(path):
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


def create(con):
    con.executescript(SCHEMA)


def create_indexes(con):
    con.executescript(INDEXES)


def set_meta(con, **kv):
    con.executemany("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                    [(k, str(v)) for k, v in kv.items()])


def get_meta(con):
    return dict(con.execute("SELECT key, value FROM meta").fetchall())


def email_evidence(con, email_id):
    """Everything needed to show one email as evidence, without touching the source data."""
    con.row_factory = sqlite3.Row
    try:
        email = con.execute("SELECT * FROM emails WHERE email_id = ?", (email_id,)).fetchone()
        if email is None:
            return None
        recips = con.execute("SELECT recipient, recipient_type FROM recipients WHERE email_id = ? "
                             "ORDER BY recipient_type, recipient", (email_id,)).fetchall()
        sources = [r[0] for r in con.execute(
            "SELECT source_file FROM source_occurrences WHERE email_id = ? ORDER BY source_file", (email_id,))]
        risk = con.execute("SELECT * FROM risk_results WHERE email_id = ?", (email_id,)).fetchone()
        return {"email": dict(email), "recipients": [dict(r) for r in recips],
                "sources": sources, "risk": dict(risk) if risk else None}
    finally:
        con.row_factory = None
