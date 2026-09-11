import pytest
from conftest import add
from fastapi.testclient import TestClient

from recall.live import configured_grader
from recall.service import create_app
from recall.storage import Database


def test_restore_keeps_history_and_cancels_queues(client, tmp_path, clock):
    client.post("/v1/sms/setup-simulator")
    card = add(client)
    client.app.state.messaging.dispatch(True, "queued-prompt")
    client.app.state.messaging.receive("HELP", "pending-inbox")
    client.post("/v1/assistant", json={"message": f"edit {card['id']} :: Null space"}).json()
    backup = client.get("/v1/backup").content
    with TestClient(create_app(tmp_path / "restored.db", clock)) as restored:
        r = restored.post(
            "/v1/restore", content=backup, headers={"Content-Type": "application/octet-stream"}
        )
        assert r.status_code == 200, r.text
        restored.app.state.messaging.tick()
        assert all(m["status"] == "cancelled" for m in restored.app.state.messaging.transcript())
        assert restored.get("/v1/settings").json()["paused"]
        assert restored.get(f"/v1/cards/{card['id']}").json()["definition"] == "Null space"
        with restored.app.state.db.engine.connect() as c:
            assert c.exec_driver_sql("PRAGMA integrity_check").scalar_one() == "ok"
            assert (
                c.exec_driver_sql("SELECT COUNT(*) FROM inbox WHERE status='pending'").scalar_one()
                == 0
            )


def test_service_lock_and_migration_backup(tmp_path):
    db = Database(tmp_path / "old.db")
    # Create an actual old schema using the shipped M0 migration.
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from recall.storage.versions.foundation import upgrade

    with db.transaction() as c:
        context = MigrationContext.configure(c)
        with Operations.context(context):
            upgrade()
        c.exec_driver_sql("CREATE TABLE alembic_version (version_num TEXT PRIMARY KEY)")
        c.exec_driver_sql("INSERT INTO alembic_version VALUES ('0001')")
    with db.service_lock():
        with pytest.raises(RuntimeError):
            with Database(db.path).service_lock():
                pass
        db.migrate()
    assert db.health()["schema"] == "0007"
    assert len(list((tmp_path / "backups").glob("*.sqlite3"))) == 1


def test_live_disabled_without_explicit_gate(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "present-but-not-authorized")
    assert configured_grader(client.app.state.core) is None
    monkeypatch.setenv("RECALL_LIVE_AI", "true")
    monkeypatch.delenv("RECALL_EVAL_REPORT", raising=False)
    with pytest.raises(KeyError):
        configured_grader(client.app.state.core)
