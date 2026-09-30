"""Additive quality workflow metadata; preserve all existing review revisions."""

SQL = (
    """CREATE TABLE plan_selections (
        plan_id TEXT PRIMARY KEY REFERENCES work_plans(id), payload TEXT NOT NULL)""",
    """CREATE TABLE preparation_exclusions (
        run_id TEXT REFERENCES llm_runs(id), sample_id TEXT REFERENCES samples(id),
        reason TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(run_id,sample_id))""",
    """CREATE TABLE quality_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT REFERENCES llm_runs(id),
        sample_id TEXT REFERENCES samples(id), action TEXT NOT NULL,
        reason TEXT NOT NULL, created_at TEXT NOT NULL)""",
    """CREATE TABLE audit_samples (
        run_id TEXT REFERENCES llm_runs(id), sample_id TEXT REFERENCES samples(id),
        seed TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(run_id,sample_id))""",
    """CREATE TABLE review_effort (
        revision INTEGER PRIMARY KEY REFERENCES reviews(revision),
        seconds REAL NOT NULL CHECK(seconds>=0))""",
    """CREATE TABLE golden_metadata (
        set_id TEXT PRIMARY KEY REFERENCES golden_sets(id), purpose TEXT NOT NULL,
        split TEXT NOT NULL, run_id TEXT REFERENCES llm_runs(id), payload TEXT NOT NULL)""",
    """CREATE TABLE preparation_history (
        id TEXT PRIMARY KEY, run_id TEXT REFERENCES llm_runs(id),
        manifest TEXT NOT NULL, created_at TEXT NOT NULL)""",
)
