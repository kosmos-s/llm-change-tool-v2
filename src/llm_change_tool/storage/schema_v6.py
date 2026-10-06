"""Additive, credential-free attempt diagnostics and measured stage durations."""

SQL = (
    """CREATE TABLE attempt_diagnostics (
        attempt_id TEXT PRIMARY KEY REFERENCES attempts(id),
        request_id TEXT, finish_reason TEXT,
        image_seconds REAL NOT NULL, provider_seconds REAL NOT NULL
    )""",
)
