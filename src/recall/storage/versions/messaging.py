from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade():
    for sql in [
        """CREATE TABLE inbox (id TEXT PRIMARY KEY, provider TEXT NOT NULL, provider_id TEXT NOT NULL,
            sender TEXT NOT NULL, body TEXT NOT NULL, received_at TEXT NOT NULL, status TEXT NOT NULL,
            lease_until TEXT, response TEXT, UNIQUE(provider,provider_id))""",
        """CREATE TABLE outbox (id TEXT PRIMARY KEY, business_key TEXT UNIQUE NOT NULL, session_id TEXT REFERENCES sessions(id),
            body TEXT NOT NULL, encoding TEXT NOT NULL, segments INTEGER NOT NULL, kind TEXT NOT NULL,
            status TEXT NOT NULL, created_at TEXT NOT NULL, lease_until TEXT, provider_id TEXT,
            accepted_at TEXT, error TEXT, dependency_id TEXT REFERENCES outbox(id), attempt_id TEXT UNIQUE NOT NULL,
            provider_segments INTEGER)""",
        """CREATE TABLE dispatch_slots (key TEXT PRIMARY KEY, local_date TEXT NOT NULL, session_id TEXT REFERENCES sessions(id),
            prompts INTEGER NOT NULL, new_cards INTEGER NOT NULL, reserved_segments INTEGER NOT NULL, status TEXT NOT NULL)""",
        "ALTER TABLE sessions ADD COLUMN pending_probe_id TEXT",
        "CREATE TABLE diagnostics (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    ]:
        op.execute(sql)
