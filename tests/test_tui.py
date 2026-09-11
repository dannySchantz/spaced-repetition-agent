import httpx
import pytest
from conftest import add
from textual.widgets import Input, Select, TabbedContent

from recall.tui.app import Flashcard, RecallApp
from recall.tui.client import Client


@pytest.mark.parametrize("size", [(80, 24), (120, 36)])
@pytest.mark.parametrize("motion", [True, False])
async def test_keyboard_study(client, size, motion):
    add(client, term="核 ∀x ∈ ℝ", definition="SECRET reference " + "long definition " * 100)
    settings = client.get("/v1/settings").json()
    client.put("/v1/settings", json={**settings, "reduced_motion": not motion})
    app = RecallApp(Client(httpx.ASGITransport(app=client.app)))
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        await pilot.click("#start")
        await pilot.pause()
        assert "SECRET" not in app.query_one("#flashcard", Flashcard).content_text
        assert app.current is not None
        await pilot.press("1")
        assert client.get("/v1/history").json() == []
        position = app.query_one("#reveal").region.y
        await pilot.press("space")
        assert app.query_one("#reveal").region.y == position
        await pilot.resize_terminal(size[0] + 5, size[1] + 2)
        await pilot.pause(0.3)
        assert "SECRET" in app.query_one("#flashcard", Flashcard).content_text
        assert app.query_one("#rate-3").region.bottom <= app.size.height
        await pilot.press("space")
        assert not app.revealed
        await pilot.press("space")
        assert app.revealed
        await pilot.press("3", "3")
        await pilot.pause()
        assert len(client.get("/v1/history").json()) == 1
        assert app.current is None
        assert app.query_one("#tabs", TabbedContent).active == "study"


async def test_typed_digits_and_space_not_shortcuts(client):
    add(client)
    app = RecallApp(Client(httpx.ASGITransport(app=client.app)))
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.click("#start")
        app.query_one("#mode", Select).value = "typed"
        await pilot.pause()
        app.query_one("#answer", Input).focus()
        await pilot.press("1", "2", "space", "3", "4")
        assert app.query_one("#answer", Input).value == "12 34"
        assert not app.revealed
        assert client.get("/v1/history").json() == []


async def test_restart_resumes_unfinished_terminal_episode(client):
    add(client)
    first = RecallApp(Client(httpx.ASGITransport(app=client.app)))
    async with first.run_test(size=(80, 24)) as pilot:
        await pilot.click("#start")
        eid = first.current["id"]
    second = RecallApp(Client(httpx.ASGITransport(app=client.app)))
    async with second.run_test(size=(80, 24)) as pilot:
        await pilot.click("#start")
        assert second.current["id"] == eid
        assert not second.revealed


async def test_resume_probe_after_terminal_restart(client):
    from conftest import start
    from textual.widgets import Static

    add(
        client, term="eigenvector", definition="A nonzero vector scaled by a linear transformation."
    )
    e = start(client)["episodes"][0]
    client.post(
        f"/v1/episodes/{e['id']}/attempts",
        json={"answer": "A vector scaled by the matrix.", "request_key": "initial"},
    )
    before = client.get("/v1/history").json()
    app = RecallApp(Client(httpx.ASGITransport(app=client.app)))
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.click("#start")
        await pilot.pause()
        assert app.pending_probe
        app.query_one("#answer", Input).value = "It must be nonzero."
        await pilot.press("enter")
        await pilot.pause()
        assert "Right after hint" in str(app.query_one("#feedback", Static).render())
        assert client.get("/v1/history").json() == before
