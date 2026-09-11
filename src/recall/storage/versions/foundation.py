"""Initial schema; subsequent milestones append migrations."""

from alembic import op

revision = "0001"
down_revision = None


def upgrade():
    op.execute("CREATE TABLE settings (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL)")
    op.get_bind().exec_driver_sql(
        """INSERT INTO settings VALUES (1, '{"timezone":"America/New_York","slots":["12:00","18:00"],"quiet_start":"21:00","quiet_end":"09:00","batch_size":3,"new_per_day":3,"daily_prompts":20,"paused":true,"opted_in":false,"reduced_motion":false,"retention":0.9,"policy_generation":1}')"""
    )
