from alembic import op

revision = "0005"
down_revision = "0004"


def upgrade():
    op.execute("""CREATE TABLE edit_proposals (id TEXT PRIMARY KEY, card_id TEXT NOT NULL REFERENCES cards(id),
        expected_revision TEXT NOT NULL REFERENCES revisions(id), data TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL)""")
