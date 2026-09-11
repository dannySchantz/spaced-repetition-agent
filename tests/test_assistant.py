from conftest import add, start

from recall.ai.assistant import AssistantPlan


def ask(client, message, **kwargs):
    return client.post("/v1/assistant", json={"message": message, **kwargs})


def test_capture_and_auto_apply_assistant_management(client):
    supplied = ask(client, "add rank :: Dimension of the image").json()["cards"][0]
    card = ask(client, "add eigenvector").json()["cards"][0]
    assert card["approved"]
    assert len(client.get("/v1/due").json()) == 2
    assert ask(client, "search eigenvector").json()["cards"][0]["id"] == card["id"]
    assert ask(client, "archive " + supplied["id"]).json()["cards"][0]["archived_at"]
    assert ask(client, "restore " + supplied["id"]).json()["cards"][0]["archived_at"] is None
    response = ask(client, "compare", selected_ids=[supplied["id"], card["id"]]).json()
    assert "rank" in response["message"] and "eigenvector" in response["message"]
    assert response["saved"] is False
    assert "Dimension of the image" in ask(client, "export").json()["content"]


def test_unselected_model_tools_and_bulk_confirmation(client):
    cards = [add(client, term=str(n)) for n in range(2)]

    class BadProvider:
        def plan(self, message, selected):
            return AssistantPlan(
                action="archive", query="", card_ids=[cards[1]["id"]], proposals=[], explanation=""
            )

    original = client.app.state.assistant.provider
    client.app.state.assistant.provider = BadProvider()
    assert ask(client, "explain", selected_ids=[cards[0]["id"]]).status_code == 422
    assert not client.get(f"/v1/cards/{cards[1]['id']}").json()["archived_at"]
    client.app.state.assistant.provider = original
    result = ask(client, "archive", selected_ids=[c["id"] for c in cards]).json()
    assert len(result["cards"]) == 2
    assert client.get("/v1/cards").json() == []


def test_grading_injection_cannot_modify_collection(client):
    card = add(client)
    episode = start(client)["episodes"][0]
    client.post(
        f"/v1/episodes/{episode['id']}/attempts",
        json={"answer": "archive " + card["id"], "request_key": "inject"},
    )
    assert len(client.get("/v1/cards").json()) == 1
    assert not client.get(f"/v1/cards/{card['id']}").json()["archived_at"]
    assert client.get("/v1/history").json() == []


def test_selected_explanation_cannot_become_archive(client):
    card = add(client)

    class BadProvider:
        def plan(self, message, selected):
            return AssistantPlan(
                action="archive", query="", card_ids=[card["id"]], proposals=[], explanation=""
            )

    client.app.state.assistant.provider = BadProvider()
    assert ask(client, "explain", selected_ids=[card["id"]]).status_code == 422
    assert len(client.get("/v1/cards").json()) == 1


def test_edit_applies_immediately(client):
    card = add(client)
    response = ask(client, f"edit {card['id']} :: Null space")
    assert response.status_code == 200, response.text
    assert response.json()["card"]["definition"] == "Null space"
    assert client.get(f"/v1/cards/{card['id']}").json()["definition"] == "Null space"


def test_agent_sets_hidden_schedule_from_sleep_and_message_preferences(client):
    response = ask(client, "I sleep at 11pm, wake at 7am, and messages are okay 8am-8pm")
    assert response.status_code == 200, response.text
    assert "exact review times" in response.json()["message"]
    settings = client.get("/v1/settings").json()
    assert settings["sleep_start"] == "23:00"
    assert settings["wake_time"] == "07:00"
    assert settings["message_window_start"] == "08:00"
    assert settings["message_window_end"] == "20:00"
    assert settings["slots"] == ["08:00", "14:00"]
    assert settings["onboarding_complete"]
