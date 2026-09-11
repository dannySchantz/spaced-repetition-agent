import pytest
from conftest import add, rate, start
from fastapi.testclient import TestClient

from recall.ai.grader import GradeBatch, ProviderResult
from recall.service import create_app


def submit(client, e, answer, kind="initial", key="answer"):
    return client.post(
        f"/v1/episodes/{e['id']}/attempts",
        json={"answer": answer, "kind": kind, "request_key": key},
    )


def test_probe_preserves_first_attempt(client):
    add(
        client, term="eigenvector", definition="A nonzero vector scaled by a linear transformation."
    )
    e = start(client)["episodes"][0]
    first = submit(client, e, "A vector scaled by the matrix.").json()
    assert first["result"]["verdict"] == "wrong"
    before = client.get("/v1/history").json()
    assert before[0]["rating"] == 1
    probe = submit(client, e, "It must be nonzero.", "probe", "probe").json()
    assert probe["result"]["verdict"] == "right"
    assert client.get("/v1/history").json() == before
    assert (
        submit(client, e, "A completely different first answer", key="repeat").json()["answer"]
        == "A vector scaled by the matrix."
    )


def test_unknown_fixture_stays_pending(client):
    add(client)
    e = start(client)["episodes"][0]
    result = submit(client, e, "Not in fixtures").json()
    assert result["status"] == "manual_pending"
    assert client.get("/v1/history").json() == []
    assert rate(client, e).status_code == 200


class BrokenProvider:
    def __init__(self, bad_ids=False):
        self.calls = 0
        self.bad_ids = bad_ids

    def grade(self, items):
        self.calls += 1
        if not self.bad_ids:
            raise TimeoutError("simulated")
        return ProviderResult(
            {
                "results": [
                    {
                        "episode_id": "unknown",
                        "verdict": "right",
                        "reason": "complete",
                        "close": False,
                        "probe": None,
                        "correction": None,
                    }
                ]
            },
            "fake",
            "fake",
            {},
        )


@pytest.mark.parametrize("bad_ids", [False, True])
def test_failures_bounded_and_saved(tmp_path, clock, bad_ids):
    provider = BrokenProvider(bad_ids)
    with TestClient(create_app(tmp_path / "failure.db", clock, provider)) as c:
        add(c)
        e = start(c)["episodes"][0]
        r = submit(c, e, "Retain this answer").json()
        assert r["answer"] == "Retain this answer" and r["status"] == "manual_pending"
        assert provider.calls == 2
        assert c.get("/v1/history").json() == []
        submit(c, e, "Retain this answer")
        assert provider.calls == 2


def test_restart_recovers_pending_and_cross_channel_wins(client, tmp_path, clock):
    add(client)
    e = start(client)["episodes"][0]
    ids = client.app.state.grading.submit(
        [{"episode_id": e["id"], "answer": "Inputs mapped to zero"}], "saved"
    )
    with TestClient(create_app(tmp_path / "test.db", clock)) as restarted:
        restarted.app.state.grading.drain()
        assert restarted.app.state.grading.get(ids)[0]["result"]["verdict"] == "right"
        assert len(restarted.get("/v1/history").json()) == 1
    assert rate(client, e).status_code == 200
    assert len(client.get("/v1/history").json()) == 1


def test_schema_rejects_probe_on_right():
    with pytest.raises(ValueError):
        GradeBatch.model_validate(
            {
                "results": [
                    {
                        "episode_id": "x",
                        "verdict": "right",
                        "reason": "complete",
                        "close": True,
                        "probe": "Why?",
                        "correction": None,
                    }
                ]
            }
        )


def test_edit_during_provider_call_discards_result(client):
    card = add(client)
    e = start(client)["episodes"][0]
    real = client.app.state.grading.provider

    class EditingProvider:
        def grade(self, items):
            client.patch(
                f"/v1/cards/{card['id']}",
                json={
                    "term": "kernel",
                    "definition": "Changed",
                    "expected_revision": card["revision_id"],
                },
            )
            return real.grade(items)

    client.app.state.grading.provider = EditingProvider()
    assert submit(client, e, "Inputs mapped to zero").json()["status"] == "cancelled"
    assert client.get("/v1/history").json() == []


def test_nonzero_fragment_is_not_a_complete_initial_answer(client):
    add(
        client, term="eigenvector", definition="A nonzero vector scaled by a linear transformation."
    )
    e = start(client)["episodes"][0]
    result = submit(client, e, "It must be nonzero.").json()
    assert result["result"]["verdict"] == "ungraded"
    assert client.get("/v1/history").json() == []


def test_malformed_multi_item_batch_applies_nothing(client):
    add(client)
    add(client, term="rank", definition="Dimension of the image")
    episodes = start(client)["episodes"]
    grading = client.app.state.grading

    class MissingResult:
        def grade(self, items):
            return ProviderResult(
                {
                    "results": [
                        {
                            "episode_id": items[0]["episode_id"],
                            "verdict": "right",
                            "reason": "complete",
                            "close": False,
                            "probe": None,
                            "correction": None,
                        }
                    ]
                },
                "fake",
                "fake",
                {},
            )

    grading.provider = MissingResult()
    ids = grading.submit([{"episode_id": e["id"], "answer": "anything"} for e in episodes], "batch")
    grading.drain()
    assert all(a["status"] == "manual_pending" for a in grading.get(ids))
    assert client.get("/v1/history").json() == []


def test_expired_second_grading_lease_goes_manual(client, clock):
    from recall.core import run

    add(client)
    e = start(client)["episodes"][0]
    grading = client.app.state.grading
    ids = grading.submit(
        [{"episode_id": e["id"], "answer": "Inputs mapped to zero"}], "lost-second-call"
    )
    with client.app.state.db.transaction() as c:
        run(
            c,
            "UPDATE attempts SET status='processing',tries=2,lease_until=:now",
            now=client.app.state.core.now(),
        )
    clock.advance(minutes=2)
    grading.drain()
    assert grading.get(ids)[0]["status"] == "manual_pending"
    assert client.get("/v1/history").json() == []


def test_responses_adapter_contract_without_network():
    from types import SimpleNamespace

    from recall.ai.grader import OpenAIProvider

    calls = []
    batch = GradeBatch.model_validate(
        {
            "results": [
                {
                    "episode_id": "e",
                    "verdict": "right",
                    "reason": "complete",
                    "close": False,
                    "probe": None,
                    "correction": None,
                }
            ]
        }
    )

    def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status="completed", output_parsed=batch, usage=None)

    provider = OpenAIProvider(
        "explicit-test-model",
        authorized=True,
        client=SimpleNamespace(responses=SimpleNamespace(parse=parse)),
    )
    assert (
        provider.grade([{"episode_id": "e", "answer": "data"}]).data["results"][0]["verdict"]
        == "right"
    )
    assert calls[0]["store"] is False and calls[0]["text_format"] is GradeBatch
    assert "tools" not in calls[0]
