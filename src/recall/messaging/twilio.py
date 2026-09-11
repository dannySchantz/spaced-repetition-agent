"""Twilio SDK adapter with strict owner routing and signed callback validation."""

from fastapi import APIRouter, HTTPException, Request, Response
from twilio.base.exceptions import TwilioRestException
from twilio.request_validator import RequestValidator

from recall.core import row


class DefinitiveSendFailure(Exception):
    pass


class TwilioAdapter:
    name = "twilio"

    def __init__(self, config, client=None):
        self.config = config
        if client is None:
            from twilio.http.http_client import TwilioHttpClient
            from twilio.rest import Client

            client = Client(
                config.account_sid,
                config.auth_token,
                http_client=TwilioHttpClient(timeout=20, max_retries=0),
            )
        self.client = client
        self.toll_free = config.toll_free

    def send(self, message):
        try:
            sent = self.client.messages.create(
                to=self.config.owner_phone,
                from_=self.config.sender_phone,
                body=message["body"],
                status_callback=f"{self.config.public_url}/webhooks/twilio/status/{message['attempt_id']}",
            )
            return sent.sid
        except TwilioRestException as exc:
            if 400 <= exc.status < 500 and exc.status not in {408, 429}:
                raise DefinitiveSendFailure(f"Provider rejected request ({exc.code})") from None
            raise


def webhook_routes(messaging, config):
    router = APIRouter(prefix="/webhooks/twilio")
    validator = RequestValidator(config.auth_token)

    async def validated(request):
        raw = await request.body()
        if len(raw) > 100000:
            raise HTTPException(413, "Webhook too large")
        form = await request.form()
        canonical = config.public_url + request.url.path
        if request.url.query:
            canonical += "?" + request.url.query
        if not validator.validate(canonical, form, request.headers.get("X-Twilio-Signature", "")):
            raise HTTPException(403, "Invalid provider signature")
        if form.get("AccountSid") != config.account_sid:
            raise HTTPException(403, "Unexpected provider account")
        return form

    @router.post("/inbound")
    async def inbound(request: Request):
        form = await validated(request)
        if form.get("From") != config.owner_phone or form.get("To") != config.sender_phone:
            raise HTTPException(403, "Unexpected sender or destination")
        if not form.get("MessageSid"):
            raise HTTPException(422, "Missing provider message ID")
        control = form.get("OptOutType", "").upper()
        body = control if control in {"STOP", "START", "HELP"} else form.get("Body", "")
        messaging.receive(
            body, form["MessageSid"], "twilio", "owner", provider_handled=bool(control)
        )
        return Response("<Response/>", media_type="application/xml")

    @router.post("/status/{attempt_id}")
    async def status(attempt_id: str, request: Request):
        form = await validated(request)
        if form.get("To") != config.owner_phone or form.get("From") != config.sender_phone:
            raise HTTPException(403, "Unexpected sender or destination")
        sid = form.get("MessageSid")
        if not sid:
            raise HTTPException(422, "Missing provider message ID")
        provider_status = form.get("MessageStatus")
        statuses = {
            "queued": "accepted",
            "accepted": "accepted",
            "sending": "accepted",
            "sent": "accepted",
            "delivered": "delivered",
            "undelivered": "failed",
            "failed": "failed",
        }
        if provider_status not in statuses:
            raise HTTPException(422, "Unknown delivery status")
        with messaging.core.db.transaction() as c:
            message = row(c, "SELECT * FROM outbox WHERE attempt_id=:id", id=attempt_id)
            if not message:
                raise HTTPException(404, "Unknown send attempt")
            if message["provider_id"] and message["provider_id"] != sid:
                raise HTTPException(409, "Provider ID mismatch")
            # Out-of-order accepted callbacks cannot undo a terminal status.
            if message["status"] in {"delivered", "failed"}:
                return Response("<Response/>", media_type="application/xml")
            segments = form.get("NumSegments")
            if segments is not None and (not segments.isdigit() or int(segments) > 1000):
                raise HTTPException(422, "Invalid segment count")
            target = statuses[provider_status]
            if target == "failed":
                messaging.fail(c, message, "Provider delivery failure", sid)
            else:
                messaging.accept(c, message["id"], sid, target, int(segments) if segments else None)
        return Response("<Response/>", media_type="application/xml")

    return router
