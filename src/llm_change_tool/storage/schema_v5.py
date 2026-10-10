"""Additive candidate identity, frozen selection and classified failures."""

SQL = (
    "CREATE TABLE sample_contents (sample_id TEXT PRIMARY KEY REFERENCES samples(id), content_hash TEXT NOT NULL)",
    "CREATE TABLE plan_policies (plan_id TEXT PRIMARY KEY REFERENCES work_plans(id), policy_hash TEXT NOT NULL)",
    """CREATE TABLE job_failures (job_id TEXT REFERENCES jobs(id), sample_id TEXT REFERENCES samples(id),
    domain TEXT NOT NULL, code TEXT NOT NULL, retryable INTEGER NOT NULL,
    PRIMARY KEY(job_id,sample_id))""",
)
