"""Additive migration: preserve frozen runs and append-only review history."""

SQL = (
    "ALTER TABLE reviews ADD COLUMN reason_en TEXT",
    """CREATE TABLE review_undo_targets (
        revision INTEGER PRIMARY KEY REFERENCES reviews(revision),
        target_revision INTEGER REFERENCES reviews(revision)
    )""",
    """CREATE TABLE job_budget_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT NOT NULL REFERENCES jobs(id),
        old_limit REAL NOT NULL, new_limit REAL NOT NULL CHECK(new_limit > 0 AND new_limit <= 1000),
        reason TEXT NOT NULL, created_at TEXT NOT NULL
    )""",
    "CREATE INDEX budget_latest ON job_budget_events(job_id,id)",
    """CREATE TABLE job_control_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT NOT NULL REFERENCES jobs(id),
        action TEXT NOT NULL, created_at TEXT NOT NULL
    )""",
)
