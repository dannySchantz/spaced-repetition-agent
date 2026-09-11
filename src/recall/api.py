from fastapi import APIRouter, Body, Response
from pydantic import Field

from . import portability
from .domain import (
    CardInput,
    CorrectionInput,
    EditInput,
    RatingInput,
    SessionInput,
    Settings,
    StrictModel,
)


class ImportInput(StrictModel):
    content: str = Field(max_length=10_000_000)
    format: str = "lines"


class AttemptInput(StrictModel):
    answer: str = Field(min_length=1, max_length=20000)
    request_key: str = Field(min_length=1, max_length=200)
    kind: str = "initial"


class SMSInput(StrictModel):
    body: str = Field(min_length=1, max_length=20000)
    message_id: str = Field(min_length=1, max_length=200)


def routes(core, grading, messaging, assistant):
    router = APIRouter(prefix="/v1")

    @router.get("/cards")
    def cards(q: str = "", archived: bool = False):
        return core.collection(q, archived)

    @router.post("/cards")
    def add(data: CardInput):
        return core.add(data)

    @router.get("/cards/{card_id}")
    def get(card_id: str):
        return core.get(card_id)

    @router.patch("/cards/{card_id}")
    def edit(card_id: str, data: EditInput):
        return core.edit(card_id, data)

    @router.post("/cards/{card_id}/archive")
    def archive(card_id: str):
        return core.archive(card_id)

    @router.post("/cards/{card_id}/restore")
    def restore_card(card_id: str):
        return core.archive(card_id, False)

    @router.get("/settings")
    def settings():
        return core.settings()

    @router.put("/settings")
    def update_settings(data: Settings):
        return core.set_settings(data.model_dump())

    @router.get("/due")
    def due():
        return core.due()

    @router.post("/sessions")
    def start(data: SessionInput):
        return core.start(data)

    @router.get("/sessions/{sid}")
    def session(sid: str):
        return core.session(sid)

    @router.post("/sessions/{sid}/more")
    def more(sid: str):
        with core.db.transaction() as c:
            core.expire(c)
            session = core.session(sid, c)
            from .core import Conflict, run

            if session["channel"] != "tui" or session["status"] in {
                "expired",
                "cancelled",
                "delivery_failed",
            }:
                raise Conflict("Only an unexpired terminal session can add due episodes")

            run(c, "UPDATE sessions SET status='awaiting_answers' WHERE id=:id", id=sid)
            core.reserve(c, sid, core.select_due(c, 10))
            return core.session(sid, c)

    @router.post("/sessions/{sid}/done")
    def done(sid: str):
        with core.db.transaction() as c:
            core.close_session(c, sid)
        return {"status": "complete"}

    @router.post("/episodes/{eid}/reveal")
    def reveal(eid: str, typed: bool = False):
        return core.reveal(eid, typed)

    @router.post("/episodes/{eid}/skip")
    def skip(eid: str):
        return core.skip(eid)

    @router.post("/episodes/{eid}/rating")
    def rate(eid: str, data: RatingInput):
        return core.rate(eid, data)

    @router.post("/reviews/{rid}/correction")
    def correct(rid: str, data: CorrectionInput):
        return core.correct(rid, data)

    @router.get("/history")
    def history():
        return core.history()

    @router.get("/export")
    def export(format: str = "json"):
        if format == "json":
            return portability.export_learning(core)
        if format not in {"csv", "markdown"}:
            raise ValueError("Choose json, csv or markdown")
        return {"content": portability.readable(core, format)}

    @router.post("/import")
    def import_data(data: ImportInput):
        import json

        if data.format == "json":
            return portability.import_learning(core, json.loads(data.content))
        if data.format not in {"csv", "lines"}:
            raise ValueError("Choose json, csv or lines")
        return portability.import_cards(core, data.content, data.format)

    @router.get("/backup")
    def backup():
        return Response(portability.snapshot(core), media_type="application/vnd.sqlite3")

    @router.post("/restore")
    def restore(content: bytes = Body(media_type="application/octet-stream")):
        return portability.restore_snapshot(core, content)

    @router.post("/episodes/{eid}/attempts")
    def attempt(eid: str, data: AttemptInput):
        ids = grading.submit(
            [{"episode_id": eid, "answer": data.answer, "kind": data.kind}], data.request_key
        )
        grading.drain()
        return grading.get(ids)[0]

    @router.get("/episodes/{eid}/attempts")
    def attempts(eid: str):
        from .core import rows

        with core.db.engine.connect() as c:
            ids = [
                v["id"]
                for v in rows(
                    c, "SELECT id FROM attempts WHERE episode_id=:id ORDER BY received_at", id=eid
                )
            ]
        return grading.get(ids)

    @router.post("/sms/setup-simulator")
    def setup_simulator():
        return messaging.enable_simulator()

    @router.post("/sms/simulate")
    def simulate(data: SMSInput):
        if messaging.adapter.name != "simulator":
            raise ValueError("Simulation requires the simulator adapter")
        messaging.receive(data.body, data.message_id)
        messaging.tick()
        return messaging.transcript()

    @router.get("/sms/transcript")
    def transcript():
        return messaging.transcript()

    @router.post("/sms/tick")
    def tick():
        if messaging.adapter.name != "simulator":
            raise ValueError("Manual tick is available only in simulation")
        messaging.tick()
        return messaging.transcript()

    @router.get("/sessions")
    def active_sessions():
        from .core import rows

        with core.db.transaction() as c:
            core.expire(c)
            return [
                core.session(v["id"], c)
                for v in rows(
                    c,
                    "SELECT id FROM sessions WHERE status NOT IN ('complete','cancelled','expired','delivery_failed')",
                )
            ]

    @router.get("/diagnostics")
    def diagnostics():
        return messaging.diagnostics()

    from .ai.assistant import AssistantInput

    @router.post("/assistant")
    def assistant_request(data: AssistantInput):
        return assistant.respond(data)

    @router.post("/cards/{card_id}/approve")
    def approve(card_id: str, expected_revision: str = Body(embed=True)):
        return assistant.approve(card_id, expected_revision)

    @router.post("/assistant/edits/{pid}/approve")
    def approve_edit(pid: str, reset_learning: bool = Body(embed=True)):
        return assistant.approve_edit(pid, reset_learning)

    return router
