"""Capture reproducible terminal screenshots using an isolated in-memory HTTP transport."""

import asyncio
import os
import tempfile
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

os.environ["RECALL_LIVE_SMS"] = "false"
os.environ["RECALL_LIVE_AI"] = "false"
os.environ.pop("RECALL_TOKEN", None)

from recall.service import create_app
from recall.tui.app import RecallApp
from recall.tui.client import Client


async def main():
    out = Path("docs/screenshots")
    out.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        with TestClient(create_app(Path(directory) / "demo.db")) as service:
            service.post(
                "/v1/cards",
                json={
                    "term": "eigenvector",
                    "definition": "A nonzero vector whose direction is unchanged by a linear transformation: Av = λv.",
                    "context": "Linear algebra",
                },
            )
            for size in [(80, 24), (120, 36)]:
                app = RecallApp(Client(httpx.ASGITransport(app=service.app)))
                async with app.run_test(size=size) as pilot:
                    await pilot.pause()
                    app.save_screenshot(f"today-{size[0]}.svg", path=str(out))
                    await pilot.click("#start")
                    await pilot.pause()
                    app.save_screenshot(f"front-{size[0]}.svg", path=str(out))
                    await pilot.press("space")
                    await pilot.pause(0.3)
                    app.save_screenshot(f"back-{size[0]}.svg", path=str(out))
                    service.post(f"/v1/sessions/{app.session['id']}/done")


asyncio.run(main())
