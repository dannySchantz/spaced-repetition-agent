"""Durable learning core."""

from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade():
    statements = [
        "CREATE TABLE cards (id TEXT PRIMARY KEY, revision_id TEXT, normalized TEXT NOT NULL, tags TEXT NOT NULL, created_at TEXT NOT NULL, archived_at TEXT)",
        "CREATE TABLE revisions (id TEXT PRIMARY KEY, card_id TEXT NOT NULL REFERENCES cards(id), number INTEGER NOT NULL, term TEXT NOT NULL, definition TEXT NOT NULL, context TEXT NOT NULL, rubric TEXT NOT NULL, approved INTEGER NOT NULL, provenance TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(card_id,number))",
        "CREATE TABLE scheduler_configs (id TEXT PRIMARY KEY, version TEXT NOT NULL, data TEXT NOT NULL)",
        "CREATE TABLE states (card_id TEXT PRIMARY KEY REFERENCES cards(id), data TEXT NOT NULL, due_at TEXT NOT NULL, version INTEGER NOT NULL, config_id TEXT NOT NULL REFERENCES scheduler_configs(id), first_presented TEXT)",
        "CREATE INDEX due_index ON states(due_at)",
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, code TEXT UNIQUE NOT NULL, channel TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, accepted_at TEXT, expires_at TEXT, request_key TEXT UNIQUE NOT NULL)",
        "CREATE TABLE episodes (id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id), card_id TEXT NOT NULL REFERENCES cards(id), revision_id TEXT NOT NULL REFERENCES revisions(id), ordinal INTEGER NOT NULL, expected_version INTEGER NOT NULL, status TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, assisted INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, UNIQUE(session_id,ordinal))",
        "CREATE UNIQUE INDEX one_active_episode ON episodes(card_id) WHERE active=1",
        "CREATE TABLE reviews (id TEXT PRIMARY KEY, episode_id TEXT UNIQUE NOT NULL REFERENCES episodes(id), card_id TEXT NOT NULL REFERENCES cards(id), rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 4), source TEXT NOT NULL, reviewed_at TEXT NOT NULL, config_id TEXT NOT NULL REFERENCES scheduler_configs(id), before_state TEXT NOT NULL, after_state TEXT NOT NULL, state_version INTEGER NOT NULL)",
        "CREATE TABLE audit (id TEXT PRIMARY KEY, target TEXT NOT NULL, action TEXT NOT NULL, reason TEXT NOT NULL, before_data TEXT, after_data TEXT, created_at TEXT NOT NULL)",
        "CREATE TABLE requests (key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result TEXT NOT NULL)",
        "CREATE TABLE skips (card_id TEXT NOT NULL REFERENCES cards(id), local_date TEXT NOT NULL, PRIMARY KEY(card_id,local_date))",
        "CREATE TRIGGER immutable_revision_update BEFORE UPDATE ON revisions BEGIN SELECT RAISE(ABORT,'revisions are immutable'); END",
    ]
    for sql in statements:
        op.execute(sql)
