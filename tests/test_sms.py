from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from conftest import add, rate
from fastapi.testclient import TestClient

from recall.messaging.policy import eligible_slot, resolve_slot
from recall.messaging.segments import estimate, split_message
from recall.service import create_app


def sms(client, body, key):
    r = client.post("/v1/sms/simulate", json={"body": body, "message_id": key})
    assert r.status_code == 200, r.text
    return r.json()


def setup(client):
    client.post("/v1/sms/setup-simulator")
    add(client)
    add(client, term="rank", definition="Dimension of the image")
    add(
        client, term="eigenvector", definition="A nonzero vector scaled by a linear transformation."
    )
    sms(client, "MORE", "more")
    return client.get("/v1/sessions").json()[0]


def test_full_session_verdicts_before_probe_duplicates(client):
    session = setup(client)
    code = session["code"]
    # Selection stable by due timestamp then UUID; look up numbers instead of assuming IDs.
    es = {e["term"]: e for e in session["episodes"]}
    body = f"{code} {es['kernel']['ordinal']}) Inputs mapped to zero; {es['rank']['ordinal']}) Dimension of the image; {es['eigenvector']['ordinal']}) A vector scaled by the matrix."
    transcript = sms(client, body, "answers")
    feedback = transcript[-1]["body"]
    assert feedback.count("Right") == 2 and feedback.count("Wrong") == 1
    assert feedback.index("Wrong") < feedback.index("What restriction")
    assert len(client.get("/v1/history").json()) == 3
    before = client.get("/v1/history").json()
    assert sms(client, body, "answers") == transcript
    sms(client, f"{code} {es['eigenvector']['ordinal']}) It must be nonzero.", "probe")
    assert client.get("/v1/history").json() == before
    assert "Right after hint" in client.get("/v1/sms/transcript").json()[-1]["body"]


def test_bad_codes_unknown_items_expiry_and_cross_channel(client, clock):
    session = setup(client)
    code = session["code"]
    e = session["episodes"][0]
    sms(client, "ZZ99 1) answer", "bad-code")
    sms(client, code + " 99) answer", "bad-item")
    assert client.get("/v1/history").json() == []
    assert rate(client, e).status_code == 200
    sms(client, f"{code} {e['ordinal']}) anything", "late-after-tui")
    assert len(client.get("/v1/history").json()) == 1
    clock.advance(hours=25)
    sms(client, code + " 2) something", "expired")
    assert len(client.get("/v1/history").json()) == 1


def test_restart_inbox_and_uncertain_not_retried(client, tmp_path, clock):
    session = setup(client)
    e = next(e for e in session["episodes"] if e["term"] == "kernel")
    client.app.state.messaging.receive(
        f"{session['code']} {e['ordinal']}) Inputs mapped to zero", "persisted"
    )
    with TestClient(create_app(tmp_path / "test.db", clock)) as restarted:
        restarted.app.state.messaging.tick()
        assert len(restarted.get("/v1/history").json()) == 1

        class Uncertain:
            name = "simulator"
            calls = 0

            def send(self, message):
                self.calls += 1
                raise TimeoutError("May have been accepted")

        adapter = Uncertain()
        restarted.app.state.messaging.adapter = adapter
        sms(restarted, "HELP", "help")
        assert adapter.calls == 1
        clock.advance(minutes=2)
        restarted.app.state.messaging.tick()
        assert adapter.calls == 1
        assert any(m["status"] == "uncertain" for m in restarted.get("/v1/sms/transcript").json())


def test_unsolicited_sms_adds_card_through_assistant(client):
    client.app.state.messaging.receive("add eigenvector to my spaced repetition", "add-card")
    client.app.state.messaging.tick()
    cards = client.get("/v1/cards").json()
    assert any(card["term"] == "eigenvector" and card["approved"] for card in cards)
    assert any(
        "Added to Recall: eigenvector" in m["body"] for m in client.get("/v1/sms/transcript").json()
    )


def test_stop_cancels_before_grading_and_resume_not_start(client):
    session = setup(client)
    e = session["episodes"][0]
    worker = client.app.state.messaging
    worker.receive(f"{session['code']} {e['ordinal']}) answer", "answer")
    worker.receive("STOP", "stop")
    worker.tick()
    assert client.get("/v1/history").json() == []
    assert not client.get("/v1/settings").json()["opted_in"]
    sms(client, "RESUME", "resume")
    assert not client.get("/v1/settings").json()["opted_in"]
    sms(client, "START", "start")
    assert client.get("/v1/settings").json()["opted_in"]


def test_budget_quiet_and_dst(client, clock):
    settings = client.get("/v1/settings").json()
    settings.update(
        opted_in=True, paused=False, slots=["01:30"], quiet_start="23:00", quiet_end="00:00"
    )
    first = datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc)
    second = datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc)
    assert eligible_slot(first, settings) is not None
    assert eligible_slot(second, settings) is None
    assert resolve_slot(
        datetime(2026, 3, 8).date(), "02:30", ZoneInfo("America/New_York")
    ) == datetime(2026, 3, 8, 7, tzinfo=timezone.utc)
    client.put("/v1/settings", json={**settings, "monthly_segments": 0})
    add(client)
    assert client.app.state.messaging.dispatch(True, "budget") is None
    settings.update(slots=["12:00"], quiet_start="21:00", quiet_end="09:00", monthly_segments=1000)
    client.put("/v1/settings", json=settings)
    assert client.app.state.messaging.dispatch() is not None
    assert client.app.state.messaging.dispatch() is not None  # same persisted slot, same session
    with client.app.state.db.engine.connect() as c:
        assert c.exec_driver_sql("SELECT COUNT(*) FROM dispatch_slots").scalar_one() == 1
    clock.advance(hours=2)
    assert eligible_slot(clock(), settings) is None


def test_segment_encoding_and_long_term(client):
    assert estimate("a" * 160) == ("GSM-7", 1)
    assert estimate("^" * 81) == ("GSM-7", 2)
    assert estimate("😀" * 36) == ("UCS-2", 2)
    assert estimate("a" * 306, True)[1] == 3
    assert all(estimate(p)[1] <= 2 for p in split_message("😀 word " * 200))
    client.post("/v1/sms/setup-simulator")
    add(client, term="字" * 200)
    assert client.app.state.messaging.dispatch(True, "long") is None


def test_multiple_probes_partial_and_bare_reply(client):
    client.post("/v1/sms/setup-simulator")
    add(
        client, term="eigenvector", definition="A nonzero vector scaled by a linear transformation."
    )
    add(
        client,
        term="idempotence",
        definition="Repeating an operation has the same effect as applying it once.",
    )
    sms(client, "MORE", "more")
    s = client.get("/v1/sessions").json()[0]
    es = {e["term"]: e for e in s["episodes"]}
    sms(
        client,
        f"{s['code']} {es['eigenvector']['ordinal']}) A vector scaled by the matrix.; {es['idempotence']['ordinal']}) An operation can be repeated.",
        "two-close",
    )
    body = client.get("/v1/sms/transcript").json()[-1]["body"]
    assert body.count("Wrong") == 2 and body.count("?") == 1
    before = client.get("/v1/history").json()
    current = client.get(f"/v1/sessions/{s['id']}").json()["pending_probe_id"]
    first = next(e for e in s["episodes"] if e["id"] == current)
    answer = (
        "It must be nonzero."
        if first["term"] == "eigenvector"
        else "Repeating an operation has the same effect as applying it once."
    )
    sms(client, f"{s['code']} {first['ordinal']}) {answer}", "first-probe")
    assert client.get(f"/v1/sessions/{s['id']}").json()["pending_probe_id"] != current
    assert client.get("/v1/history").json() == before


def test_stop_precedes_older_start_and_stale_prompt(client, clock):
    client.post("/v1/sms/setup-simulator")
    add(client)
    worker = client.app.state.messaging
    worker.receive("START", "old-start")
    worker.receive("STOP", "new-stop")
    worker.tick()
    assert not client.get("/v1/settings").json()["opted_in"]
    worker.receive("START", "fresh-start")
    worker.process_inbox()
    sid = worker.dispatch()
    assert sid
    clock.advance(hours=6)
    worker.send_one()
    worker.send_one()
    assert (
        next(m for m in client.get("/v1/sms/transcript").json() if "Define:" in m["body"])["status"]
        == "cancelled"
    )
    assert client.get("/v1/history").json() == []


def test_daily_limit_and_skip_no_false_failure(client, clock):
    client.post("/v1/sms/setup-simulator")
    cfg = client.get("/v1/settings").json()
    client.put("/v1/settings", json={**cfg, "daily_prompts": 1})
    add(client)
    add(client, term="rank", definition="Dimension of the image")
    sms(client, "MORE", "m1")
    s = client.get("/v1/sessions").json()[0]
    assert len(s["episodes"]) == 1
    sms(client, f"{s['code']} SKIP 1", "skip")
    sms(client, f"{s['code']} DONE", "done")
    sms(client, "MORE", "m2")
    assert len([m for m in client.get("/v1/sms/transcript").json() if "Define:" in m["body"]]) == 1
    assert client.get("/v1/history").json() == []


def test_unsent_prompt_cancelled_after_tui_completion(client):
    client.post("/v1/sms/setup-simulator")
    add(client)
    worker = client.app.state.messaging
    sid = worker.dispatch(True, "before-tui")
    session = client.get(f"/v1/sessions/{sid}").json()
    assert rate(client, session["episodes"][0]).status_code == 200
    worker.send_one()
    assert worker.transcript()[0]["status"] == "cancelled"
    assert len(client.get("/v1/history").json()) == 1


def test_stop_during_grade_discards_result(client):
    session = setup(client)
    e = next(e for e in session["episodes"] if e["term"] == "kernel")
    original = client.app.state.grading.provider

    class StopDuringGrade:
        def grade(self, items):
            client.app.state.messaging.receive("STOP", "stop-during-call")
            return original.grade(items)

    client.app.state.grading.provider = StopDuringGrade()
    sms(client, f"{session['code']} {e['ordinal']}) Inputs mapped to zero", "answer")
    assert client.get("/v1/history").json() == []
    assert len(client.app.state.messaging.transcript()) == 1


def test_short_sms_label_restores_long_card_suitability(client):
    client.post("/v1/sms/setup-simulator")
    card = add(client, term="字" * 200)
    assert card["sms_suitable"] is False
    assert client.app.state.messaging.dispatch(True, "too-long") is None
    response = client.patch(
        f"/v1/cards/{card['id']}",
        json={
            "term": card["term"],
            "definition": card["definition"],
            "sms_label": "Concise label",
            "expected_revision": card["revision_id"],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["sms_suitable"] is True
    assert client.app.state.messaging.dispatch(True, "fits")
    assert "Concise label" in client.app.state.messaging.transcript()[0]["body"]
