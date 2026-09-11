from contextlib import contextmanager
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, text


class Database:
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.engine = create_engine(
            f"sqlite:///{self.path}", connect_args={"check_same_thread": False}
        )

        @event.listens_for(self.engine, "connect")
        def configure(conn, _):
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("PRAGMA busy_timeout=5000")

    @contextmanager
    def service_lock(self):
        import fcntl

        path = self.path.with_suffix(".service.lock")
        with path.open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("Another Recall service owns this database") from None
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def local_snapshot(self):
        import sqlite3
        from datetime import datetime, timezone
        from uuid import uuid4

        directory = self.path.parent / "backups"
        directory.mkdir(exist_ok=True)
        destination = directory / (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            + "-"
            + uuid4().hex[:8]
            + ".sqlite3"
        )
        with sqlite3.connect(self.path) as source, sqlite3.connect(destination) as target:
            source.backup(target)
        destination.chmod(0o600)
        for old in sorted(
            directory.glob("*.sqlite3"), key=lambda p: p.stat().st_mtime, reverse=True
        )[7:]:
            old.unlink()
        return destination

    def migrate(self):
        from .versions import (
            assistant,
            foundation,
            grading,
            learning,
            messaging,
            operations,
            sms_labels,
        )

        with self.engine.connect() as check:
            previous = MigrationContext.configure(check).get_current_revision()
        if previous is not None and previous != sms_labels.revision:
            self.local_snapshot()
        with self.transaction() as conn:
            context = MigrationContext.configure(conn)
            current = context.get_current_revision()
            migrations = [
                foundation,
                learning,
                grading,
                messaging,
                assistant,
                operations,
                sms_labels,
            ]
            if current is not None and current not in [m.revision for m in migrations]:
                raise RuntimeError(f"Unsupported schema: {current}")
            for migration in migrations:
                if current == migration.down_revision:
                    with Operations.context(context):
                        migration.upgrade()
                    context._ensure_version_table()
                    conn.execute(text("DELETE FROM alembic_version"))
                    conn.execute(
                        text("INSERT INTO alembic_version VALUES (:version)"),
                        {"version": migration.revision},
                    )
                    current = migration.revision
        self.path.chmod(0o600)

    @contextmanager
    def transaction(self):
        with self.engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    @contextmanager
    def read_transaction(self):
        with self.engine.connect() as conn:
            conn.exec_driver_sql("BEGIN")
            try:
                yield conn
            finally:
                conn.rollback()

    def health(self):
        with self.engine.connect() as conn:
            return {
                "status": "ok",
                "schema": conn.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one(),
                "database": str(self.path),
            }
