from alembic import op

revision = "0006"
down_revision = "0005"


def upgrade():
    op.execute("ALTER TABLE inbox ADD COLUMN provider_handled INTEGER NOT NULL DEFAULT 0")
    op.execute("""CREATE TABLE ai_usage (id TEXT PRIMARY KEY, month TEXT NOT NULL, provider TEXT NOT NULL,
        model TEXT NOT NULL, reserved_tokens INTEGER NOT NULL, actual_tokens INTEGER, created_at TEXT NOT NULL)""")
