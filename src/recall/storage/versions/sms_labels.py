from alembic import op

revision = "0007"
down_revision = "0006"


def upgrade():
    op.execute("ALTER TABLE revisions ADD COLUMN sms_label TEXT")
