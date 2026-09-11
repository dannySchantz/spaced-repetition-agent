import os
import secrets
from contextlib import asynccontextmanager

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from .api import routes
from .config import database_path
from .core import Conflict, Core
from .storage import Database


def create_app(path=None, clock=None, provider=None, worker=False, adapter=None):
    db = Database(path or database_path())
    from .live import LiveConfig
    from .messaging.twilio import TwilioAdapter, webhook_routes

    live_config = None
    if adapter is None and os.getenv("RECALL_LIVE_SMS", "false") == "true":
        if (
            len(os.getenv("RECALL_TOKEN", "")) < 32
            or os.getenv("RECALL_OWNER_CONSENT") != "yes"
            or int(os.getenv("RECALL_MONTHLY_SMS_SEGMENTS", "0")) <= 0
        ):
            raise ValueError(
                "Live SMS requires a strong owner token, explicit consent and a monthly segment allowance"
            )
        live_config = LiveConfig.from_env()
        adapter = TwilioAdapter(live_config)
    elif isinstance(adapter, TwilioAdapter):
        live_config = adapter.config

    @asynccontextmanager
    async def lifespan(app):
        from contextlib import nullcontext

        with db.service_lock() if worker else nullcontext():
            db.migrate()
            if worker:
                from .live import configured_grader

                configured = configured_grader(core)
                if configured:
                    grading.provider = configured
                    from .live import BudgetedAssistant

                    assistant.provider = BudgetedAssistant(configured)
                with db.transaction() as c:
                    from .core import dump, row, run

                    previous = row(c, "SELECT value FROM diagnostics WHERE key='adapter'")
                    if (previous is None and messaging.adapter.name != "simulator") or (
                        previous and previous["value"] != messaging.adapter.name
                    ):
                        settings = core.settings(c)
                        settings.update(paused=True, opted_in=False)
                        if messaging.adapter.name == "twilio":
                            settings["monthly_segments"] = int(
                                os.environ["RECALL_MONTHLY_SMS_SEGMENTS"]
                            )
                        run(c, "UPDATE settings SET data=:data WHERE id=1", data=dump(settings))
                        run(c, "UPDATE outbox SET status='cancelled' WHERE status='queued'")
                        run(c, "UPDATE outbox SET status='uncertain' WHERE status='sending'")
                    run(
                        c,
                        "INSERT INTO diagnostics VALUES ('adapter',:name) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        name=messaging.adapter.name,
                    )
            import asyncio

            stop = asyncio.Event()

            async def work():
                while not stop.is_set():
                    try:
                        await asyncio.to_thread(messaging.tick)
                    except Exception:
                        import logging

                        logging.getLogger("recall").error(
                            "Worker tick failed; inspect diagnostics (details withheld from logs)"
                        )
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=1)
                    except TimeoutError:
                        pass

            task = asyncio.create_task(work()) if worker else None
            try:
                yield
            finally:
                if task:
                    stop.set()
                    await task
                db.engine.dispose()

    app = FastAPI(title="Recall", lifespan=lifespan)
    app.state.db = db
    core = Core(db, clock) if clock else Core(db)
    app.state.core = core
    from .ai.workflow import Grading

    grading = Grading(core, provider)
    app.state.grading = grading
    from .ai.assistant import Assistant

    assistant = Assistant(core)
    from .messaging.worker import Messaging

    messaging = Messaging(core, grading, adapter, assistant)
    app.state.messaging = messaging
    app.state.assistant = assistant

    @app.post("/auth/login")
    def login(request: Request, data: dict = Body(...)):
        from .auth import login as do_login
        return {"access_token": do_login(request, str(data.get("email", "")), str(data.get("password", "")), str(data.get("website", ""))), "token_type": "bearer", "expires_in": 86400}

    def authenticate(authorization: str = Header(default="")):
        token = os.getenv("RECALL_TOKEN", "")
        from .auth import valid_session
        presented = authorization.removeprefix("Bearer ")
        if token and not secrets.compare_digest(authorization, f"Bearer {token}") and not valid_session(presented):
            raise HTTPException(401, "Invalid owner token")

    @app.get("/v1/health", dependencies=[Depends(authenticate)])
    def health():
        return db.health()

    @app.get("/healthz")
    def healthz():
        """Unauthenticated platform probe; detailed diagnostics remain protected."""
        return {"status": "ok"}

    @app.exception_handler(Conflict)
    async def conflict_handler(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(KeyError)
    async def missing_handler(request, exc):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def invalid_handler(request, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    app.include_router(
        routes(core, grading, messaging, assistant), dependencies=[Depends(authenticate)]
    )
    if live_config:
        app.include_router(webhook_routes(messaging, live_config))
    return app
