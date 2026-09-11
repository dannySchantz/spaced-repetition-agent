import json
from datetime import timedelta
from zoneinfo import ZoneInfo

from recall.core import Conflict, dump, row, rows, run, uid
from recall.domain import RatingInput, SessionInput, stamp

from .parser import parse
from .policy import eligible_slot, next_opportunity
from .segments import estimate, split_message


class Simulator:
    name = "simulator"

    def send(self, message):
        return "SIM-" + message["attempt_id"]


class Messaging:
    def __init__(self, core, grading, adapter=None, assistant=None):
        self.core, self.grading, self.adapter = core, grading, adapter or Simulator()
        self.assistant = assistant
        grading.on_result = self.feedback
        grading.on_failure = self.failed_grading

    def enable_simulator(self):
        if self.adapter.name != "simulator":
            raise ValueError("Simulator setup cannot enable live delivery")
        return self.core.set_settings({**self.core.settings(), "paused": False, "opted_in": True})

    def queue(self, c, key, body, sid=None, kind="feedback", dependency=None):
        settings = self.core.settings(c)
        if not settings["opted_in"]:
            return None
        # Two-segment jobs with labels; preserve verdict order before any teaching.
        parts = split_message(
            body, max_segments=2, toll_free=getattr(self.adapter, "toll_free", False)
        )
        if len(parts) > 1 and sid:
            code = row(c, "SELECT code FROM sessions WHERE id=:id", id=sid)["code"]
            parts = split_message(body, max_segments=1)
            parts = [
                part if i == 0 else f"{code} continued: {part}" for i, part in enumerate(parts)
            ]
        last = dependency
        for index, part in enumerate(parts):
            business = f"{key}:{index}"
            existing = row(c, "SELECT id FROM outbox WHERE business_key=:key", key=business)
            if existing:
                last = existing["id"]
                continue
            encoding, segments = estimate(part, getattr(self.adapter, "toll_free", False))
            month = self.core.now()[:7]
            used = run(
                c,
                "SELECT COALESCE(SUM(segments),0) FROM outbox WHERE substr(created_at,1,7)=:month AND status NOT IN ('cancelled','failed')",
                month=month,
            ).scalar_one()
            if used + segments > settings["monthly_segments"]:
                return last
            oid = uid()
            run(
                c,
                """INSERT INTO outbox (id,business_key,session_id,body,encoding,segments,kind,status,created_at,dependency_id,attempt_id)
                VALUES (:id,:key,:sid,:body,:encoding,:segments,:kind,'queued',:now,:dep,:attempt)""",
                id=oid,
                key=business,
                sid=sid,
                body=part,
                encoding=encoding,
                segments=segments,
                kind=kind,
                now=self.core.now(),
                dep=last,
                attempt=uid(),
            )
            last = oid
        return last

    def dispatch(self, manual=False, key=None):
        core = self.core
        with core.db.transaction() as c:
            core.expire(c)
            settings = core.settings(c)
            if not settings["opted_in"] or settings["paused"]:
                return None
            slot = key if manual else eligible_slot(core.clock(), settings)
            if slot is None:
                return None
            slot = ("manual:" + slot) if manual else slot
            old = row(c, "SELECT session_id FROM dispatch_slots WHERE key=:key", key=slot)
            if old:
                return old["session_id"]
            if row(
                c,
                "SELECT id FROM sessions WHERE channel='sms' AND status NOT IN ('complete','cancelled','expired','delivery_failed')",
            ):
                return None
            local_date = core.clock().astimezone(ZoneInfo(settings["timezone"])).date().isoformat()
            used = row(
                c,
                "SELECT COALESCE(SUM(prompts),0) AS prompts,COALESCE(SUM(new_cards),0) AS new_cards FROM dispatch_slots WHERE local_date=:date AND status!='failed'",
                date=local_date,
            )
            # Include new TUI presentations in collection-wide new-card allowance.
            presented = rows(
                c, "SELECT first_presented FROM states WHERE first_presented IS NOT NULL"
            )
            from datetime import datetime

            new_today = sum(
                datetime.fromisoformat(r["first_presented"])
                .astimezone(ZoneInfo(settings["timezone"]))
                .date()
                .isoformat()
                == local_date
                for r in presented
            )
            count = min(settings["batch_size"], settings["daily_prompts"] - used["prompts"])
            new_left = max(0, settings["new_per_day"] - new_today)
            selected = []
            for card in core.due(c):
                card["display"] = card["sms_label"] or card["term"]
                if card["context"] and not card["sms_label"]:
                    card["display"] += f" ({card['context']})"
                if len(selected) >= count:
                    break
                if row(
                    c,
                    "SELECT card_id FROM skips WHERE card_id=:id AND local_date=:date",
                    id=card["id"],
                    date=local_date,
                ):
                    continue
                if card["first_presented"] is None and new_left <= 0:
                    continue
                proposal = selected + [card]
                body = (
                    "XXXX Define: "
                    + " ".join(f"{i}) {v['display']}" for i, v in enumerate(proposal, 1))
                    + ". Reply XXXX 1) answer; 2) answer."
                )
                if estimate(body, getattr(self.adapter, "toll_free", False))[1] > 2:
                    continue
                selected.append(card)
                if card["first_presented"] is None:
                    new_left -= 1
            if not selected:
                return None
            month = core.now()[:7]
            used_segments = run(
                c,
                "SELECT COALESCE(SUM(segments),0) FROM outbox WHERE substr(created_at,1,7)=:month AND status NOT IN ('failed','cancelled')",
                month=month,
            ).scalar_one()
            # Reserve prompt + bounded verdict/probe exchanges, before presenting cards.
            reserved = 2 + len(selected) * 6
            outstanding = run(
                c,
                "SELECT COALESCE(SUM(reserved_segments),0) FROM dispatch_slots d JOIN sessions s ON s.id=d.session_id WHERE s.status NOT IN ('complete','cancelled','expired','delivery_failed')",
            ).scalar_one()
            if used_segments + outstanding + reserved > settings["monthly_segments"]:
                return None
            session = core.start(
                SessionInput(request_key="sms:" + slot, count=1, channel="sms"), c, selected
            )
            code = session["code"]
            body = (
                f"{code} Define: "
                + " ".join(f"{i}) {v['display']}" for i, v in enumerate(selected, 1))
                + f". Reply {code} 1) answer; 2) answer."
            )
            run(
                c,
                "UPDATE sessions SET status='queued',accepted_at=NULL,expires_at=NULL WHERE id=:id",
                id=session["id"],
            )
            self.queue(c, "prompt:" + session["id"], body, session["id"], "prompt")
            run(
                c,
                "INSERT INTO dispatch_slots VALUES (:key,:date,:sid,:count,:new,:reserved,'queued')",
                key=slot,
                date=local_date,
                sid=session["id"],
                count=len(selected),
                new=sum(v["first_presented"] is None for v in selected),
                reserved=reserved,
            )
            return session["id"]

    def receive(
        self, body, provider_id, provider="simulator", sender="owner", provider_handled=False
    ):
        if not body.strip() or len(body) > 20000:
            raise ValueError("Message must contain 1–20000 characters")
        with self.core.db.transaction() as c:
            old = row(
                c,
                "SELECT * FROM inbox WHERE provider=:provider AND provider_id=:pid",
                provider=provider,
                pid=provider_id,
            )
            if old:
                return old["id"]
            mid = uid()
            run(
                c,
                "INSERT INTO inbox (id,provider,provider_id,sender,body,received_at,status) VALUES (:id,:provider,:pid,:sender,:body,:now,'pending')",
                id=mid,
                provider=provider,
                pid=provider_id,
                sender=sender,
                body=body,
                now=self.core.now(),
            )
            if provider_handled:
                run(c, "UPDATE inbox SET provider_handled=1 WHERE id=:id", id=mid)
            # STOP is immediate and bypasses the grader and all response queues.
            if body.strip().upper() == "STOP":
                settings = self.core.settings(c)
                settings.update(opted_in=False, paused=True, provider_opted_out=True)
                run(
                    c,
                    "UPDATE inbox SET status='cancelled' WHERE status IN ('pending','processing') AND id!=:id",
                    id=mid,
                )
                run(c, "UPDATE settings SET data=:data WHERE id=1", data=dump(settings))
                run(c, "UPDATE outbox SET status='cancelled' WHERE status='queued'")
                for s in rows(
                    c,
                    "SELECT id FROM sessions WHERE channel='sms' AND status NOT IN ('complete','expired','cancelled')",
                ):
                    self.core.close_session(c, s["id"], "cancelled")
                run(c, "UPDATE inbox SET status='done' WHERE id=:id", id=mid)
                self.core.audit(c, "settings", "stop", "Owner opt-out")
            return mid

    def reply(self, mid, body, sid=None):
        with self.core.db.transaction() as c:
            handled = row(c, "SELECT provider_handled FROM inbox WHERE id=:id", id=mid)
            if not handled or not handled["provider_handled"]:
                self.queue(c, "reply:" + mid, body, sid)
            run(c, "UPDATE inbox SET status='done',response=:body WHERE id=:id", id=mid, body=body)

    def process_inbox(self):
        core = self.core
        with core.db.transaction() as c:
            core.expire(c)
            message = row(
                c,
                "SELECT * FROM inbox WHERE status='pending' OR (status='processing' AND lease_until<=:now) ORDER BY received_at LIMIT 1",
                now=core.now(),
            )
            if not message:
                return False
            run(
                c,
                "UPDATE inbox SET status='processing',lease_until=:lease WHERE id=:id",
                id=message["id"],
                lease=stamp(core.clock() + timedelta(seconds=60)),
            )
        mid = message["id"]
        try:
            parsed = parse(message["body"])
            command = parsed.command
            if command == "START" and parsed.code is None:
                with core.db.transaction() as c:
                    settings = core.settings(c)
                    settings["provider_opted_out"] = False
                    run(c, "UPDATE settings SET data=:data WHERE id=1", data=dump(settings))
                core.set_settings({**core.settings(), "opted_in": True, "paused": False})
                self.reply(mid, "Recall resumed. MORE starts a review; STOP opts out.")
                return True
            settings = core.settings()
            # An owner-initiated assistant message is an explicit request to use Recall.
            # Preserve STOP: a provider opt-out still requires START before any reply.
            if (
                command == "ASSISTANT"
                and not settings["opted_in"]
                and not settings["provider_opted_out"]
            ):
                core.set_settings({**settings, "opted_in": True, "paused": False})
                settings = core.settings()
            if not settings["opted_in"]:
                with core.db.transaction() as c:
                    run(c, "UPDATE inbox SET status='done' WHERE id=:id", id=mid)
                return True
            if parsed.code is None:
                if command == "ASSISTANT":
                    if self.assistant is None:
                        raise ValueError("Assistant is unavailable")
                    from recall.ai.assistant import AssistantInput

                    result = self.assistant.respond(AssistantInput(message=parsed.bare or ""))
                    cards = result.get("cards", [])
                    response = (
                        "Added to Recall: " + ", ".join(c["term"] for c in cards[:8]) + "."
                        if cards
                        else result.get("message", "Recall updated.")
                    )
                    self.reply(mid, response[:1500])
                elif command == "HELP":
                    self.reply(
                        mid,
                        "Recall: MORE, PAUSE, RESUME, STOP. Answers need code and number: K4 1) definition. K4 DONE closes a session.",
                    )
                elif command in {"PAUSE", "RESUME"}:
                    core.set_settings({**core.settings(), "paused": command == "PAUSE"})
                    if command == "PAUSE":
                        with core.db.transaction() as c:
                            run(
                                c,
                                "UPDATE outbox SET status='cancelled' WHERE kind='prompt' AND status='queued'",
                            )
                            for s in rows(
                                c, "SELECT id FROM sessions WHERE channel='sms' AND status='queued'"
                            ):
                                core.close_session(c, s["id"], "cancelled")
                    self.reply(mid, "Recall paused." if command == "PAUSE" else "Recall resumed.")
                elif command == "MORE":
                    if not self.dispatch(True, mid):
                        self.reply(
                            mid,
                            "No batch available: check active session, due cards, pause or allowance in Recall.",
                        )
                    else:
                        with core.db.transaction() as c:
                            run(c, "UPDATE inbox SET status='done' WHERE id=:id", id=mid)
                return True
            with core.db.engine.connect() as c:
                found = row(
                    c,
                    "SELECT id FROM sessions WHERE code=:code AND channel='sms'",
                    code=parsed.code,
                )
            if not found:
                raise ValueError("Unknown session code; no reviews changed.")
            session = core.session(found["id"])
            sid = session["id"]
            if session["status"] not in {"awaiting_answers", "tutoring"}:
                raise ValueError(f"{parsed.code} session is closed or not yet accepted.")
            episodes = {e["ordinal"]: e for e in session["episodes"]}
            if command == "DONE":
                with core.db.transaction() as c:
                    core.close_session(c, sid)
                self.reply(mid, parsed.code + " Done; unanswered items stay due.", sid)
                return True
            if command:
                if parsed.ordinal not in episodes:
                    raise ValueError("Unknown item number; no reviews changed.")
                e = episodes[parsed.ordinal]
                if command == "SKIP":
                    core.skip(e["id"])
                    result = "Skipped; still due."
                elif command == "SHOW":
                    if e["rating"] is None:
                        result = core.reveal(e["id"], True)["definition"]
                    else:
                        with core.db.engine.connect() as c:
                            result = row(
                                c,
                                "SELECT definition FROM revisions WHERE id=:id",
                                id=e["revision_id"],
                            )["definition"]
                elif command == "EXPLAIN":
                    if e["rating"] is None:
                        result = core.reveal(e["id"], True)["definition"]
                    else:
                        with core.db.engine.connect() as c:
                            result = row(
                                c,
                                "SELECT definition FROM revisions WHERE id=:id",
                                id=e["revision_id"],
                            )["definition"]
                elif command == "RATE":
                    r = core.rate(
                        e["id"],
                        RatingInput(
                            rating=parsed.rating,
                            expected_version=e["expected_version"],
                            request_key=mid,
                        ),
                    )
                    result = f"Recorded rating {r['rating']}."
                else:
                    raise ValueError("Unknown command")
                self.reply(mid, f"{parsed.code} {parsed.ordinal}. {result}", sid)
                return True
            pending_probe = session.get("pending_probe_id")
            eligible = [e for e in episodes.values() if e["active"] or e["id"] == pending_probe]
            answers = parsed.answers
            if parsed.bare:
                if len(eligible) != 1:
                    raise ValueError("Number each answer; multiple items are pending.")
                answers = {eligible[0]["ordinal"]: parsed.bare}
            if not answers or any(n not in episodes for n in answers):
                raise ValueError("Unknown item number; no reviews changed.")
            submissions = []
            completed = []
            for n, answer in sorted(answers.items()):
                e = episodes[n]
                if e["id"] == pending_probe:
                    kind = "probe"
                elif e["status"] == "probe_pending":
                    raise ValueError("Answer the current probe before the queued probe.")
                elif e["rating"] is not None:
                    completed.append(
                        f"{n}. {'Right' if e['rating'] >= 3 else 'Wrong'} (already recorded)"
                    )
                    continue
                elif not e["active"]:
                    raise ValueError("That item is closed; no reviews changed.")
                else:
                    kind = "initial"
                submissions.append({"episode_id": e["id"], "answer": answer, "kind": kind})
            if submissions:
                self.grading.submit(submissions, mid)
            if completed and not submissions:
                self.reply(mid, parsed.code + " " + "; ".join(completed), sid)
            else:
                with core.db.transaction() as c:
                    run(c, "UPDATE inbox SET status='done' WHERE id=:id", id=mid)
        except (ValueError, KeyError, Conflict) as exc:
            self.reply(mid, str(exc))
        return True

    def feedback(self, c, attempts):
        # Invoked inside the same transaction as review application.
        for sid in sorted({a["session_id"] for a in attempts}):
            session = self.core.session(sid, c)
            if session["channel"] != "sms":
                continue
            submitted = sorted(
                [a for a in attempts if a["session_id"] == sid], key=lambda a: a["ordinal"]
            )
            verdicts = []
            corrections = []
            for a in submitted:
                grade = a["result"]
                n = a["ordinal"]
                if grade["verdict"] != "ungraded":
                    label = "Right" if grade["verdict"] == "right" else "Wrong"
                    if a["kind"] == "probe":
                        label += " after hint"
                    verdicts.append(f"{n}. {label}")
                if grade["correction"] and not grade["probe"]:
                    corrections.append(f"{n}: {grade['correction']}")
            body = session["code"] + " " + ("; ".join(verdicts) if verdicts else "Pending.")
            pending = [str(e["ordinal"]) for e in session["episodes"] if e["active"]]
            if pending:
                body += " Pending: " + ", ".join(pending) + "."
            probe = row(
                c,
                "SELECT e.id,e.ordinal,a.result FROM episodes e JOIN attempts a ON a.episode_id=e.id AND a.kind='initial' WHERE e.session_id=:sid AND e.status='probe_pending' ORDER BY e.ordinal LIMIT 1",
                sid=sid,
            )
            if probe:
                run(
                    c,
                    "UPDATE sessions SET pending_probe_id=:eid,status='tutoring' WHERE id=:id",
                    eid=probe["id"],
                    id=sid,
                )
                corrections.append(f"{probe['ordinal']}: {json.loads(probe['result'])['probe']}")
            else:
                run(c, "UPDATE sessions SET pending_probe_id=NULL WHERE id=:id", id=sid)
                if not pending:
                    run(c, "UPDATE sessions SET status='complete' WHERE id=:id", id=sid)
            if corrections:
                body += " " + " ".join(corrections)
            self.queue(c, "grade:" + ":".join(a["id"] for a in submitted), body, sid)

    def send_one(self):
        core = self.core
        with core.db.transaction() as c:
            run(
                c,
                "UPDATE outbox SET status='uncertain',error='Lease expired after possible acceptance' WHERE status='sending' AND lease_until<=:now",
                now=core.now(),
            )
            settings = core.settings(c)
            if not settings["opted_in"]:
                run(c, "UPDATE outbox SET status='cancelled' WHERE status='queued'")
                return False
            message = row(
                c,
                """SELECT o.* FROM outbox o WHERE o.status='queued'
                AND (:paused=0 OR o.kind!='prompt') AND (dependency_id IS NULL OR EXISTS
                (SELECT 1 FROM outbox d WHERE d.id=o.dependency_id AND d.status IN ('accepted','delivered')))
                ORDER BY o.created_at,o.rowid LIMIT 1""",
                paused=int(settings["paused"]),
            )
            if not message:
                return False
            if message["kind"] == "prompt":
                session = row(c, "SELECT * FROM sessions WHERE id=:id", id=message["session_id"])
                dispatch = row(
                    c, "SELECT key FROM dispatch_slots WHERE session_id=:id", id=session["id"]
                )
                stale_slot = (
                    dispatch
                    and not dispatch["key"].startswith("manual:")
                    and eligible_slot(core.clock(), settings) != dispatch["key"]
                )
                changed_episode = row(
                    c,
                    "SELECT id FROM episodes WHERE session_id=:sid AND active=0",
                    sid=session["id"],
                )
                if session["status"] != "queued" or stale_slot or changed_episode:
                    run(c, "UPDATE outbox SET status='cancelled' WHERE id=:id", id=message["id"])
                    core.close_session(c, session["id"], "cancelled")
                    run(
                        c,
                        "UPDATE dispatch_slots SET status='failed' WHERE session_id=:id",
                        id=session["id"],
                    )
                    return True
            run(
                c,
                "UPDATE outbox SET status='sending',lease_until=:lease WHERE id=:id",
                id=message["id"],
                lease=stamp(core.clock() + timedelta(seconds=60)),
            )
        try:
            provider_id = self.adapter.send(message)
        except Exception as exc:
            from .twilio import DefinitiveSendFailure

            if isinstance(exc, DefinitiveSendFailure):
                with core.db.transaction() as c:
                    self.fail(c, message, str(exc))
                return True
            with core.db.transaction() as c:
                run(
                    c,
                    "UPDATE outbox SET status='uncertain',error=:error WHERE id=:id",
                    id=message["id"],
                    error=type(exc).__name__,
                )
            return True
        with core.db.transaction() as c:
            self.accept(c, message["id"], provider_id)
        return True

    def accept(self, c, oid, provider_id, status="accepted", segments=None):
        message = row(c, "SELECT * FROM outbox WHERE id=:id", id=oid)
        if not message:
            raise KeyError("Unknown outbound attempt")
        if message["status"] in {"delivered", "failed", "cancelled"}:
            return
        if message["provider_id"] and message["provider_id"] != provider_id:
            raise Conflict("Provider ID mismatch")
        run(
            c,
            "UPDATE outbox SET status=:status,provider_id=:pid,accepted_at=COALESCE(accepted_at,:now),lease_until=NULL,provider_segments=COALESCE(:segments,provider_segments) WHERE id=:id",
            id=oid,
            status=status,
            pid=provider_id,
            now=self.core.now(),
            segments=segments,
        )
        if message["kind"] == "prompt":
            run(
                c,
                "UPDATE sessions SET status='awaiting_answers',accepted_at=:now,expires_at=:expiry WHERE id=:id AND status='queued'",
                id=message["session_id"],
                now=self.core.now(),
                expiry=stamp(self.core.clock() + timedelta(hours=24)),
            )
            run(
                c,
                "UPDATE dispatch_slots SET status='accepted' WHERE session_id=:sid",
                sid=message["session_id"],
            )

    def tick(self):
        with self.core.db.transaction() as c:
            self.core.expire(c)
            run(
                c,
                "INSERT INTO diagnostics VALUES ('last_worker_tick',:now) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                now=self.core.now(),
            )
        for _ in range(100):
            if not self.process_inbox():
                break
        self.grading.drain()
        self.dispatch()
        for _ in range(100):
            if not self.send_one():
                break

    def transcript(self):
        with self.core.db.engine.connect() as c:
            return rows(
                c,
                "SELECT id,body,status,encoding,segments,provider_id FROM outbox ORDER BY created_at,rowid",
            )

    def diagnostics(self):
        with self.core.db.engine.connect() as c:
            return {
                **self.core.db.health(),
                "last_worker_tick": row(
                    c, "SELECT value FROM diagnostics WHERE key='last_worker_tick'"
                ),
                "outbox": rows(c, "SELECT status,COUNT(*) AS count FROM outbox GROUP BY status"),
                "pending_grades": run(
                    c,
                    "SELECT COUNT(*) FROM attempts WHERE status IN ('pending','processing','manual_pending')",
                ).scalar_one(),
                "next_delivery_at": next_opportunity(self.core.clock(), self.core.settings(c)),
                "adapter": self.adapter.name,
                "last_backup": row(c, "SELECT value FROM diagnostics WHERE key='last_backup'"),
                "last_provider_error": row(
                    c,
                    "SELECT error FROM outbox WHERE error IS NOT NULL ORDER BY created_at DESC LIMIT 1",
                ),
                "estimated_segments": run(
                    c,
                    "SELECT COALESCE(SUM(segments),0) FROM outbox WHERE status NOT IN ('cancelled','failed')",
                ).scalar_one(),
                "provider_segments": run(
                    c, "SELECT COALESCE(SUM(provider_segments),0) FROM outbox"
                ).scalar_one(),
                "ai_tokens": run(
                    c,
                    "SELECT COALESCE(SUM(COALESCE(actual_tokens,reserved_tokens)),0) FROM ai_usage",
                ).scalar_one(),
            }

    def fail(self, c, message, error, provider_id=None):
        run(
            c,
            "UPDATE outbox SET status='failed',error=:error,provider_id=COALESCE(:pid,provider_id),lease_until=NULL WHERE id=:id",
            id=message["id"],
            error=error,
            pid=provider_id,
        )
        run(
            c,
            "UPDATE outbox SET status='cancelled' WHERE dependency_id=:id AND status='queued'",
            id=message["id"],
        )
        if message["kind"] == "prompt":
            self.core.close_session(c, message["session_id"], "delivery_failed")
            run(
                c,
                "UPDATE dispatch_slots SET status='failed',reserved_segments=0 WHERE session_id=:id",
                id=message["session_id"],
            )
            # Unaccepted new presentations can be offered again; accepted failures keep exposure history.
            if not message["accepted_at"]:
                run(
                    c,
                    """UPDATE states SET first_presented=NULL WHERE card_id IN
                    (SELECT card_id FROM episodes WHERE session_id=:sid) AND
                    NOT EXISTS(SELECT 1 FROM reviews WHERE reviews.card_id=states.card_id) AND
                    NOT EXISTS(SELECT 1 FROM episodes e WHERE e.card_id=states.card_id AND e.session_id!=:sid)""",
                    sid=message["session_id"],
                )

    def failed_grading(self, c, attempts):
        for a in attempts:
            current = row(c, "SELECT status FROM attempts WHERE id=:id", id=a["id"])
            if current["status"] != "manual_pending":
                continue
            e = self.core.episode(c, a["episode_id"])
            session = self.core.session(e["session_id"], c)
            if session["channel"] == "sms":
                self.queue(
                    c,
                    "grading-failed:" + a["id"],
                    f"{session['code']} {e['ordinal']}. Pending: grading unavailable. Please use manual rating in Recall.",
                    session["id"],
                )
