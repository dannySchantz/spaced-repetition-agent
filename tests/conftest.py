from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from recall.service import create_app


class Clock:
    def __init__(self):
        self.value = datetime(2026, 9, 11, 16, tzinfo=timezone.utc)

    def __call__(self):
        return self.value

    def advance(self, **kwargs):
        self.value += timedelta(**kwargs)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def client(tmp_path, clock, monkeypatch):
    monkeypatch.delenv("RECALL_TOKEN", raising=False)
    with TestClient(create_app(tmp_path / "test.db", clock)) as value:
        yield value


def add(client, term="kernel", definition="Inputs mapped to zero", **kwargs):
    r = client.post("/v1/cards", json={"term": term, "definition": definition, **kwargs})
    assert r.status_code == 200, r.text
    return r.json()


def start(client, key="session"):
    r = client.post("/v1/sessions", json={"request_key": key})
    assert r.status_code == 200, r.text
    return r.json()


def rate(client, episode, rating=3, key="rating"):
    return client.post(
        f"/v1/episodes/{episode['id']}/rating",
        json={
            "rating": rating,
            "expected_version": episode["expected_version"],
            "request_key": key,
        },
    )


@pytest.fixture(autouse=True)
def disable_live_integrations(monkeypatch):
    monkeypatch.setenv("RECALL_LIVE_SMS", "false")
    monkeypatch.setenv("RECALL_LIVE_AI", "false")
    monkeypatch.delenv("RECALL_TOKEN", raising=False)
