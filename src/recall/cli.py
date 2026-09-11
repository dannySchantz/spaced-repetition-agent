import os

import httpx
import typer

from .config import database_path, server_url

app = typer.Typer(invoke_without_command=True)


def request(method, path, **kwargs):
    token = os.getenv("RECALL_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with httpx.Client(base_url=server_url(), headers=headers, timeout=30) as client:
        response = client.request(method, f"/v1/{path}", **kwargs)
        response.raise_for_status()
        return response.json()


@app.callback()
def main(ctx: typer.Context):
    if ctx.invoked_subcommand is None:
        from .tui.app import RecallApp

        RecallApp().run()


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8765):
    import uvicorn

    from .service import create_app

    if host not in {"127.0.0.1", "localhost", "::1"} and len(os.getenv("RECALL_TOKEN", "")) < 32:
        raise typer.BadParameter("Remote binding requires RECALL_TOKEN of at least 32 characters")
    uvicorn.run(create_app(worker=True), host=host, port=port, workers=1)


@app.command()
def init():
    """Initialize the local service database before starting the service."""
    from .storage import Database

    db = Database(database_path())
    with db.service_lock():
        db.migrate()
    typer.echo(db.health())
    db.engine.dispose()


@app.command()
def doctor():
    typer.echo(request("GET", "diagnostics"))


@app.command()
def add(term: str, definition: str, context: str = "", draft: bool = False):
    typer.echo(
        request(
            "POST",
            "cards",
            json={
                "term": term,
                "definition": definition,
                "context": context,
                "approved": not draft,
            },
        )
    )


@app.command(name="list")
def list_cards(query: str = "", archived: bool = False):
    typer.echo(request("GET", "cards", params={"q": query, "archived": archived}))


@app.command()
def review(count: int = 10):
    """Review manually through the shared service."""
    from uuid import uuid4

    session = request("POST", "sessions", json={"request_key": str(uuid4()), "count": count})
    try:
        for e in session["episodes"]:
            typer.echo(f"\n{e['term']} ({e['context']})")
            typer.prompt("Press Enter to reveal", default="", show_default=False)
            typer.echo(request("POST", f"episodes/{e['id']}/reveal")["definition"])
            rating = typer.prompt("1 Again / 2 Hard / 3 Good / 4 Easy / 0 Skip", type=int)
            if rating == 0:
                request("POST", f"episodes/{e['id']}/skip")
            else:
                typer.echo(
                    request(
                        "POST",
                        f"episodes/{e['id']}/rating",
                        json={
                            "rating": rating,
                            "expected_version": e["expected_version"],
                            "request_key": str(uuid4()),
                        },
                    )
                )
    finally:
        request("POST", f"sessions/{session['id']}/done")


@app.command(name="import")
def import_file(source: str, format: str = "lines"):
    from pathlib import Path

    typer.echo(
        request("POST", "import", json={"content": Path(source).read_text(), "format": format})
    )


@app.command()
def export(destination: str, format: str = "json"):
    import json
    from pathlib import Path

    value = request("GET", "export", params={"format": format})
    with Path(destination).open("x") as output:
        output.write(
            json.dumps(value, ensure_ascii=False, indent=2)
            if format == "json"
            else value["content"]
        )
    typer.echo(destination)


@app.command()
def backup(destination: str):
    from pathlib import Path

    token = os.getenv("RECALL_TOKEN", "")
    response = httpx.get(
        server_url() + "/v1/backup",
        headers={"Authorization": f"Bearer {token}"} if token else {},
        timeout=30,
    )
    response.raise_for_status()
    with Path(destination).open("xb") as output:
        output.write(response.content)
    typer.echo(destination)


@app.command()
def restore(source: str):
    from pathlib import Path

    typer.echo(
        request(
            "POST",
            "restore",
            content=Path(source).read_bytes(),
            headers={"Content-Type": "application/octet-stream"},
        )
    )


sms_app = typer.Typer(help="Local SMS simulator; never sends real texts")
app.add_typer(sms_app, name="sms")


@sms_app.command()
def simulate(body: str = "MORE", message_id: str = ""):
    from uuid import uuid4

    for message in request(
        "POST", "sms/simulate", json={"body": body, "message_id": message_id or str(uuid4())}
    ):
        typer.echo(f"[{message['status']}] {message['body']}")


@sms_app.command(name="setup")
def setup_sms_simulator():
    typer.echo(request("POST", "sms/setup-simulator"))


@app.command()
def assistant(
    message: str,
    selected_id: list[str] = typer.Option([], "--select"),
    confirm_selection: bool = False,
):
    typer.echo(
        request(
            "POST",
            "assistant",
            json={
                "message": message,
                "selected_ids": selected_id,
                "confirm_selection": confirm_selection,
            },
        )
    )


@app.command()
def approve(card_id: str, revision_id: str):
    typer.echo(request("POST", f"cards/{card_id}/approve", json={"expected_revision": revision_id}))


@app.command(name="approve-edit")
def approve_edit(proposal_id: str, reset_learning: bool):
    typer.echo(
        request(
            "POST",
            f"assistant/edits/{proposal_id}/approve",
            json={"reset_learning": reset_learning},
        )
    )
