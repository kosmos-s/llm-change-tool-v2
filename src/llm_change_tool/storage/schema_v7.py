"""Audited image-token estimates without rewriting frozen run settings."""

SQL = (
    """CREATE TABLE job_reservation_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT NOT NULL REFERENCES jobs(id),
        image_tokens INTEGER CHECK (image_tokens IS NULL OR image_tokens BETWEEN 1 AND 2000000),
        reason TEXT NOT NULL, created_at TEXT NOT NULL
    )""",
    "CREATE INDEX reservation_job ON job_reservation_events(job_id,id)",
)
