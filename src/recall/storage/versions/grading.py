from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade():
    op.execute("""CREATE TABLE attempts (id TEXT PRIMARY KEY, episode_id TEXT NOT NULL REFERENCES episodes(id),
        kind TEXT NOT NULL CHECK(kind IN ('initial','probe')), answer TEXT NOT NULL, received_at TEXT NOT NULL,
        request_key TEXT UNIQUE NOT NULL, group_id TEXT NOT NULL, status TEXT NOT NULL, tries INTEGER NOT NULL DEFAULT 0,
        lease_until TEXT, lease_token TEXT, result TEXT, provider TEXT, model TEXT, prompt_version TEXT,
        usage TEXT, error TEXT, UNIQUE(episode_id,kind))""")
    op.execute("CREATE INDEX pending_attempts ON attempts(status,lease_until)")
    op.execute(
        "CREATE TRIGGER immutable_initial_answer BEFORE UPDATE OF answer ON attempts BEGIN SELECT RAISE(ABORT,'answers are immutable'); END"
    )
