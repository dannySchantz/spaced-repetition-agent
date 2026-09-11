from types import SimpleNamespace
from urllib.parse import urlencode

from conftest import add
from fastapi.testclient import TestClient
from twilio.base.exceptions import TwilioRestException
from twilio.request_validator import RequestValidator

from recall.live import LiveConfig
from recall.messaging.twilio import TwilioAdapter
from recall.service import create_app

CONFIG = LiveConfig(
    "ACtest", "test-token", "+15555550101", "+15555550102", "https://recall.example"
)


class FakeMessages:
    def __init__(self):
        self.calls = []
        self.error = None

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(sid="SMsent")


def post_signed(client, path, params, valid=True):
    signature = RequestValidator(CONFIG.auth_token).compute_signature(
        CONFIG.public_url + path, params
    )
    return client.post(
        path,
        content=urlencode(params),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Twilio-Signature": signature if valid else "invalid",
        },
    )


def base():
    return {
        "AccountSid": CONFIG.account_sid,
        "From": CONFIG.owner_phone,
        "To": CONFIG.sender_phone,
        "MessageSid": "SMin",
        "Body": "HELP",
    }


def test_signatures_owner_dedup_and_control(tmp_path, clock):
    fake = FakeMessages()
    with TestClient(
        create_app(
            tmp_path / "live.db",
            clock,
            adapter=TwilioAdapter(CONFIG, SimpleNamespace(messages=fake)),
        )
    ) as c:
        params = base()
        assert post_signed(c, "/webhooks/twilio/inbound", params, False).status_code == 403
        assert (
            post_signed(
                c, "/webhooks/twilio/inbound", {**params, "From": "+15555550999"}
            ).status_code
            == 403
        )
        assert post_signed(c, "/webhooks/twilio/inbound", params).status_code == 200
        assert post_signed(c, "/webhooks/twilio/inbound", params).status_code == 200
        with c.app.state.db.engine.connect() as conn:
            assert conn.exec_driver_sql("SELECT COUNT(*) FROM inbox").scalar_one() == 1
        cfg = c.get("/v1/settings").json()
        c.put("/v1/settings", json={**cfg, "opted_in": True, "paused": False})
        assert (
            post_signed(
                c,
                "/webhooks/twilio/inbound",
                {**params, "MessageSid": "SMstop", "Body": "anything", "OptOutType": "STOP"},
            ).status_code
            == 200
        )
        c.app.state.messaging.tick()
        assert not fake.calls
        assert c.get("/v1/settings").json()["provider_opted_out"]
        c.put("/v1/settings", json={**cfg, "opted_in": True, "paused": False})
        assert not c.get("/v1/settings").json()["opted_in"]
        post_signed(
            c,
            "/webhooks/twilio/inbound",
            {**params, "MessageSid": "SMstart", "Body": "START", "OptOutType": "START"},
        )
        c.app.state.messaging.tick()
        assert c.get("/v1/settings").json()["opted_in"]
        assert not fake.calls  # Provider-handled START is not acknowledged twice.


def test_send_status_reconciliation_and_no_regression(tmp_path, clock):
    fake = FakeMessages()
    with TestClient(
        create_app(
            tmp_path / "live.db",
            clock,
            adapter=TwilioAdapter(CONFIG, SimpleNamespace(messages=fake)),
        )
    ) as c:
        cfg = c.get("/v1/settings").json()
        c.put("/v1/settings", json={**cfg, "opted_in": True, "paused": False})
        add(c)
        c.app.state.messaging.dispatch(True, "batch")
        c.app.state.messaging.send_one()
        assert len(fake.calls) == 1
        sent = fake.calls[0]
        assert sent["to"] == CONFIG.owner_phone and sent["from_"] == CONFIG.sender_phone
        path = sent["status_callback"].removeprefix(CONFIG.public_url)
        params = {
            "AccountSid": CONFIG.account_sid,
            "From": CONFIG.sender_phone,
            "To": CONFIG.owner_phone,
            "MessageSid": "SMsent",
            "MessageStatus": "delivered",
            "NumSegments": "1",
        }
        assert post_signed(c, path, params).status_code == 200
        assert post_signed(c, path, {**params, "MessageStatus": "sent"}).status_code == 200
        assert c.app.state.messaging.transcript()[0]["status"] == "delivered"
        assert post_signed(c, path, {**params, "MessageSid": "SMother"}).status_code == 409


def test_definitive_rejection_releases_reservation(tmp_path, clock):
    fake = FakeMessages()
    fake.error = TwilioRestException(400, "https://api.twilio.com", msg="Rejected", code=21211)
    with TestClient(
        create_app(
            tmp_path / "live.db",
            clock,
            adapter=TwilioAdapter(CONFIG, SimpleNamespace(messages=fake)),
        )
    ) as c:
        cfg = c.get("/v1/settings").json()
        c.put("/v1/settings", json={**cfg, "opted_in": True, "paused": False})
        add(c)
        worker = c.app.state.messaging
        sid = worker.dispatch(True, "batch")
        worker.send_one()
        assert worker.transcript()[0]["status"] == "failed"
        assert c.get(f"/v1/sessions/{sid}").json()["status"] == "delivery_failed"
        assert len(c.get("/v1/due").json()) == 1
        worker.send_one()
        assert len(fake.calls) == 1


def test_callback_before_send_response_keeps_delivered(tmp_path, clock):
    fake = FakeMessages()
    with TestClient(
        create_app(
            tmp_path / "race.db",
            clock,
            adapter=TwilioAdapter(CONFIG, SimpleNamespace(messages=fake)),
        )
    ) as c:
        cfg = c.get("/v1/settings").json()
        c.put("/v1/settings", json={**cfg, "opted_in": True, "paused": False})
        add(c)
        worker = c.app.state.messaging
        worker.dispatch(True, "callback-race")

        def create(**kwargs):
            path = kwargs["status_callback"].removeprefix(CONFIG.public_url)
            response = post_signed(
                c,
                path,
                {
                    "AccountSid": CONFIG.account_sid,
                    "From": CONFIG.sender_phone,
                    "To": CONFIG.owner_phone,
                    "MessageSid": "SMrace",
                    "MessageStatus": "delivered",
                },
            )
            assert response.status_code == 200
            return SimpleNamespace(sid="SMrace")

        fake.create = create
        worker.send_one()
        assert worker.transcript()[0]["status"] == "delivered"


def test_old_start_replay_cannot_override_new_stop(tmp_path, clock):
    fake = FakeMessages()
    with TestClient(
        create_app(
            tmp_path / "replay.db",
            clock,
            adapter=TwilioAdapter(CONFIG, SimpleNamespace(messages=fake)),
        )
    ) as c:
        params = {**base(), "MessageSid": "SMstart", "Body": "START", "OptOutType": "START"}
        post_signed(c, "/webhooks/twilio/inbound", params)
        c.app.state.messaging.tick()
        post_signed(
            c,
            "/webhooks/twilio/inbound",
            {**params, "MessageSid": "SMstop", "Body": "STOP", "OptOutType": "STOP"},
        )
        post_signed(c, "/webhooks/twilio/inbound", params)
        c.app.state.messaging.tick()
        assert c.get("/v1/settings").json()["provider_opted_out"]
        assert not c.get("/v1/settings").json()["opted_in"]
