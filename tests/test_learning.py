import json
from concurrent.futures import ThreadPoolExecutor

from conftest import add, rate, start
from fastapi.testclient import TestClient

from recall.service import create_app


def test_restart_retry_and_backup(client, tmp_path, clock):
    card = add(client)
    e = start(client)["episodes"][0]
    result = rate(client, e).json()
    due = client.get(f"/v1/cards/{card['id']}").json()["due_at"]
    assert rate(client, e).json() == result
    assert rate(client, e, key="another retry").json() == result
    assert len(client.get("/v1/history").json()) == 1
    with TestClient(create_app(tmp_path / "test.db", clock)) as restarted:
        assert restarted.get(f"/v1/cards/{card['id']}").json()["due_at"] == due
    backup = client.get("/v1/backup").content
    with TestClient(create_app(tmp_path / "restore.db", clock)) as restored:
        r = restored.post(
            "/v1/restore", content=backup, headers={"Content-Type": "application/octet-stream"}
        )
        assert r.status_code == 200, r.text
        assert restored.get(f"/v1/cards/{card['id']}").json()["due_at"] == due
        assert restored.get("/v1/settings").json()["paused"]
        assert len(restored.get("/v1/history").json()) == 1


def test_stale_revision_and_state(client):
    card = add(client)
    e = start(client)["episodes"][0]
    bad = {**e, "expected_version": 19}
    assert rate(client, bad).status_code == 409
    assert (
        client.patch(
            f"/v1/cards/{card['id']}",
            json={
                "term": "kernel",
                "definition": "null space",
                "expected_revision": card["revision_id"],
            },
        ).status_code
        == 200
    )
    assert rate(client, e).status_code == 409
    assert client.get("/v1/history").json() == []


def test_correction_and_legitimate_second_episode(client, clock):
    add(client)
    session = start(client)
    e = session["episodes"][0]
    review = rate(client, e).json()
    r = client.post(
        f"/v1/reviews/{review['id']}/correction",
        json={
            "rating": 1,
            "expected_version": 1,
            "request_key": "correct",
            "reason": "Incorrect grade",
        },
    )
    assert r.status_code == 200, r.text
    assert len(client.get("/v1/history").json()) == 1
    clock.advance(minutes=2)
    more = client.post(f"/v1/sessions/{session['id']}/more").json()
    assert len(more["episodes"]) == 2
    assert rate(client, more["episodes"][1], key="second").status_code == 200
    assert (
        client.post(
            f"/v1/reviews/{review['id']}/correction",
            json={"rating": 4, "expected_version": 3, "request_key": "late", "reason": "too late"},
        ).status_code
        == 409
    )


def test_concurrent_duplicate_reservations_and_ratings(client):
    add(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        sessions = list(pool.map(lambda n: start(client, f"s{n}"), range(2)))
    episodes = [e for s in sessions for e in s["episodes"]]
    assert len(episodes) == 1
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda n: rate(client, episodes[0], key=f"r{n}"), range(2)))
    assert all(r.status_code == 200 for r in results)
    assert len(client.get("/v1/history").json()) == 1


def test_drafts_skip_expiry_and_portability(client, clock, tmp_path):
    add(client, term="draft", approved=False)
    approved = add(client)
    assert len(client.get("/v1/due").json()) == 1
    e = start(client)["episodes"][0]
    assert "definition" not in e
    clock.advance(hours=25)
    assert rate(client, e).status_code == 409
    assert client.get("/v1/history").json() == []
    assert client.post(f"/v1/cards/{approved['id']}/archive").status_code == 200
    assert client.get("/v1/due").json() == []
    client.post(f"/v1/cards/{approved['id']}/restore")
    data = client.get("/v1/export").json()
    with TestClient(create_app(tmp_path / "import.db", clock)) as fresh:
        assert (
            fresh.post(
                "/v1/import", json={"format": "json", "content": json.dumps(data)}
            ).status_code
            == 200
        )
        assert len(fresh.get("/v1/cards").json()) == 2
    assert (
        client.post(
            "/v1/import", json={"content": "rank :: Dimension of image\nbad line"}
        ).status_code
        == 422
    )
    assert len(client.get("/v1/cards").json()) == 2


def test_new_allowance_is_shared_and_expired_session_cannot_reopen(client, clock):
    for n in range(5):
        add(client, term=f"new {n}")
    first = start(client)
    assert len(first["episodes"]) == 3
    assert start(client, "other")["episodes"] == []
    clock.advance(hours=25)
    assert client.post(f"/v1/sessions/{first['id']}/more").status_code == 409
    assert client.get("/v1/history").json() == []


def test_json_export_is_one_consistent_snapshot(client, monkeypatch):
    from recall import portability
    from recall.domain import CardInput

    add(client)
    original = portability.rows
    inserted = False

    def interleaved(conn, sql, **params):
        nonlocal inserted
        result = original(conn, sql, **params)
        if sql == "SELECT * FROM cards" and not inserted:
            inserted = True
            client.app.state.core.add(
                CardInput(term="concurrent", definition="Created during export")
            )
        return result

    monkeypatch.setattr(portability, "rows", interleaved)
    backup = client.get("/v1/export").json()
    assert len(backup["tables"]["cards"]) == 1
    assert len(backup["tables"]["revisions"]) == 1
    assert len(client.get("/v1/cards").json()) == 2
