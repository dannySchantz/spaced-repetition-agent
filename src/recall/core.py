"""Application-owned learning operations. All mutations use short serialized transactions."""

import hashlib
import json
import secrets
import unicodedata
from datetime import datetime, timedelta
from importlib.metadata import version
from uuid import uuid4
from zoneinfo import ZoneInfo

from fsrs import Card, Rating, Scheduler
from sqlalchemy import text

from .domain import CardInput, Settings, stamp, utcnow


def uid():
    return str(uuid4())


def run(conn, sql, **params):
    return conn.execute(text(sql), params)


def row(conn, sql, **params):
    value = run(conn, sql, **params).mappings().first()
    return dict(value) if value else None


def rows(conn, sql, **params):
    return [dict(r) for r in run(conn, sql, **params).mappings()]


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class Conflict(ValueError):
    pass


class Core:
    def __init__(self, db, clock=utcnow):
        self.db, self.clock = db, clock

    def now(self):
        return stamp(self.clock())

    def settings(self, conn=None):
        if conn is None:
            with self.db.engine.connect() as c:
                return self.settings(c)
        return Settings.model_validate_json(
            run(conn, "SELECT data FROM settings WHERE id=1").scalar_one()
        ).model_dump()

    def set_settings(self, data):
        value = Settings.model_validate(data).model_dump()
        with self.db.transaction() as c:
            old = self.settings(c)
            value["provider_opted_out"] = old["provider_opted_out"]
            if old["provider_opted_out"]:
                value["opted_in"] = False
            value["policy_generation"] = old["policy_generation"] + 1
            run(c, "UPDATE settings SET data=:data WHERE id=1", data=dump(value))
            self.audit(c, "settings", "preferences", "Owner settings", old, value)
        return value

    def audit(self, c, target, action, reason, before=None, after=None):
        run(
            c,
            "INSERT INTO audit VALUES (:id,:target,:action,:reason,:before,:after,:now)",
            id=uid(),
            target=target,
            action=action,
            reason=reason,
            before=dump(before),
            after=dump(after),
            now=self.now(),
        )

    def config(self, c):
        scheduler = Scheduler(desired_retention=self.settings(c)["retention"], enable_fuzzing=False)
        data = scheduler.to_json()
        key = hashlib.sha256((version("fsrs") + data).encode()).hexdigest()
        run(
            c,
            "INSERT OR IGNORE INTO scheduler_configs VALUES (:id,:version,:data)",
            id=key,
            version=version("fsrs"),
            data=data,
        )
        return key

    def add(self, value: CardInput, c=None):
        if c is None:
            with self.db.transaction() as conn:
                return self.add(value, conn)
        card_id, revision_id = uid(), uid()
        run(
            c,
            "INSERT INTO cards VALUES (:id,:rev,:normalized,:tags,:now,NULL)",
            id=card_id,
            rev=revision_id,
            normalized=self.normalize(value.term),
            tags=dump(value.tags),
            now=self.now(),
        )
        self.revision(c, card_id, revision_id, 1, value)
        state = Card(card_id=uuid4().int >> 64, due=self.clock())
        run(
            c,
            "INSERT INTO states VALUES (:id,:data,:due,0,:config,NULL)",
            id=card_id,
            data=state.to_json(),
            due=stamp(state.due),
            config=self.config(c),
        )
        return self.get(card_id, c)

    @staticmethod
    def normalize(term):
        return " ".join(unicodedata.normalize("NFKC", term).casefold().split())

    def revision(self, c, card_id, rev, number, value):
        run(
            c,
            "INSERT INTO revisions (id,card_id,number,term,definition,context,rubric,approved,provenance,created_at,sms_label) VALUES (:id,:card,:number,:term,:definition,:context,:rubric,:approved,:provenance,:now,:sms_label)",
            id=rev,
            card=card_id,
            number=number,
            term=value.term,
            definition=value.definition,
            context=value.context,
            rubric=dump(value.rubric),
            approved=int(value.approved),
            provenance=value.provenance,
            sms_label=value.sms_label,
            now=self.now(),
        )

    def get(self, card_id, c=None):
        if c is None:
            with self.db.engine.connect() as conn:
                return self.get(card_id, conn)
        result = row(
            c,
            """SELECT cards.*, r.term,r.definition,r.context,r.rubric,r.approved,r.number,r.provenance,r.sms_label,
                         s.due_at,s.version,s.first_presented FROM cards JOIN revisions r ON r.id=cards.revision_id
                         JOIN states s ON s.card_id=cards.id WHERE cards.id=:id""",
            id=card_id,
        )
        if result is None:
            raise KeyError("Card not found")
        result["tags"] = json.loads(result["tags"])
        result["rubric"] = json.loads(result["rubric"])
        from .messaging.segments import estimate

        display = result["sms_label"] or result["term"]
        if result["context"] and not result["sms_label"]:
            display += f" ({result['context']})"
        result["sms_suitable"] = (
            estimate(f"XXXX Define: 1) {display}. Reply XXXX 1) answer.")[1] <= 2
        )
        return result

    def collection(self, query="", archived=False):
        with self.db.engine.connect() as c:
            all_cards = [
                self.get(r["id"], c) for r in rows(c, "SELECT id FROM cards ORDER BY created_at,id")
            ]
        query = self.normalize(query)
        return [
            r
            for r in all_cards
            if (archived or not r["archived_at"])
            and query in self.normalize(" ".join([r["term"], r["context"], *r["tags"]]))
        ]

    def edit(self, card_id, value, c=None):
        if c is None:
            with self.db.transaction() as conn:
                return self.edit(card_id, value, conn)
        if c is not None:
            old = self.get(card_id, c)
            if old["revision_id"] != value.expected_revision:
                raise Conflict("Definition changed; reload before editing")
            rev = uid()
            self.revision(c, card_id, rev, old["number"] + 1, value)
            run(
                c,
                "UPDATE cards SET revision_id=:rev,normalized=:normalized,tags=:tags WHERE id=:id",
                rev=rev,
                normalized=self.normalize(value.term),
                tags=dump(value.tags),
                id=card_id,
            )
            run(
                c,
                "UPDATE episodes SET active=0,status='cancelled' WHERE card_id=:id AND active=1",
                id=card_id,
            )
            if value.reset_learning:
                state = Card(due=self.clock())
                run(
                    c,
                    "UPDATE states SET data=:data,due_at=:due,version=version+1,config_id=:cfg,first_presented=NULL WHERE card_id=:id",
                    data=state.to_json(),
                    due=self.now(),
                    cfg=self.config(c),
                    id=card_id,
                )
            self.audit(c, card_id, "edit", "Owner revision", old, value.model_dump())
            return self.get(card_id, c)

    def archive(self, card_id, archived=True):
        with self.db.transaction() as c:
            self.get(card_id, c)
            run(
                c,
                "UPDATE cards SET archived_at=:at WHERE id=:id",
                id=card_id,
                at=self.now() if archived else None,
            )
            if archived:
                run(
                    c,
                    "UPDATE episodes SET active=0,status='cancelled' WHERE card_id=:id AND active=1",
                    id=card_id,
                )
            self.audit(c, card_id, "archive" if archived else "restore", "Explicit owner selection")
            return self.get(card_id, c)

    def due(self, c=None):
        if c is None:
            with self.db.engine.connect() as conn:
                return self.due(conn)
        return rows(
            c,
            """SELECT cards.id, r.term,r.context,r.sms_label,s.due_at,s.version,s.first_presented FROM cards
            JOIN revisions r ON r.id=cards.revision_id JOIN states s ON s.card_id=cards.id
            WHERE cards.archived_at IS NULL AND r.approved=1 AND s.due_at<=:now
            AND NOT EXISTS(SELECT 1 FROM episodes e WHERE e.card_id=cards.id AND e.active=1)
            ORDER BY CASE WHEN s.first_presented IS NULL THEN 2 WHEN json_extract(s.data,'$.state') IN (1,3) THEN 0 ELSE 1 END,s.due_at,cards.id""",
            now=self.now(),
        )

    def expire(self, c):
        for session in rows(
            c,
            "SELECT id FROM sessions WHERE status NOT IN ('complete','expired','cancelled') AND expires_at<=:now",
            now=self.now(),
        ):
            self.close_session(c, session["id"], "expired")

    def start(self, data, c=None, selected=None):
        if c is None:
            with self.db.transaction() as conn:
                return self.start(data, conn, selected)
        if c is not None:
            self.expire(c)
            old = row(c, "SELECT id FROM sessions WHERE request_key=:key", key=data.request_key)
            if old:
                return self.session(old["id"], c)
            sid, code = uid(), secrets.token_hex(2).upper()
            while row(c, "SELECT id FROM sessions WHERE code=:code", code=code):
                code = secrets.token_hex(2).upper()
            run(
                c,
                "INSERT INTO sessions (id,code,channel,status,created_at,accepted_at,expires_at,request_key) VALUES (:id,:code,:channel,:status,:now,:now,:expiry,:key)",
                id=sid,
                code=code,
                channel=data.channel,
                status="awaiting_answers",
                now=self.now(),
                expiry=stamp(self.clock() + timedelta(hours=24)),
                key=data.request_key,
            )
            if selected is None:
                selected = self.select_due(c, data.count)
            self.reserve(c, sid, selected)
            if not row(c, "SELECT id FROM episodes WHERE session_id=:id", id=sid):
                self.close_session(c, sid)
            return self.session(sid, c)

    def select_due(self, c, count):
        settings = self.settings(c)
        today = self.clock().astimezone(ZoneInfo(settings["timezone"])).date()
        presented = rows(c, "SELECT first_presented FROM states WHERE first_presented IS NOT NULL")
        used = sum(
            datetime.fromisoformat(r["first_presented"])
            .astimezone(ZoneInfo(settings["timezone"]))
            .date()
            == today
            for r in presented
        )
        new_left = max(0, settings["new_per_day"] - used)
        selected = []
        for card in self.due(c):
            if len(selected) >= count:
                break
            if card["first_presented"] is None:
                if new_left <= 0:
                    continue
                new_left -= 1
            selected.append(card)
        return selected

    def reserve(self, c, sid, selected):
        ordinal = run(
            c, "SELECT COALESCE(MAX(ordinal),0) FROM episodes WHERE session_id=:id", id=sid
        ).scalar_one()
        for item in selected:
            card = self.get(item["id"], c)
            ordinal += 1
            run(
                c,
                "INSERT INTO episodes VALUES (:id,:sid,:card,:rev,:ordinal,:version,'awaiting_answer',1,0,:now)",
                id=uid(),
                sid=sid,
                card=card["id"],
                rev=card["revision_id"],
                ordinal=ordinal,
                version=card["version"],
                now=self.now(),
            )
            run(
                c,
                "UPDATE states SET first_presented=COALESCE(first_presented,:now) WHERE card_id=:id",
                now=self.now(),
                id=card["id"],
            )

    def session(self, sid, c=None):
        if c is None:
            with self.db.transaction() as conn:
                self.expire(conn)
                return self.session(sid, conn)
        result = row(c, "SELECT * FROM sessions WHERE id=:id", id=sid)
        if not result:
            raise KeyError("Session not found")
        result["episodes"] = rows(
            c,
            """SELECT e.*,r.term,r.context,v.rating,v.id AS review_id FROM episodes e
            JOIN revisions r ON r.id=e.revision_id LEFT JOIN reviews v ON v.episode_id=e.id
            WHERE e.session_id=:id ORDER BY e.ordinal""",
            id=sid,
        )
        return result

    def close_session(self, c, sid, status="complete"):
        run(c, "UPDATE sessions SET status=:status WHERE id=:id", id=sid, status=status)
        run(
            c,
            "UPDATE episodes SET active=0,status=CASE WHEN status='graded' THEN status ELSE 'closed' END WHERE session_id=:id",
            id=sid,
        )

    def episode(self, c, eid):
        e = row(c, "SELECT * FROM episodes WHERE id=:id", id=eid)
        if not e:
            raise KeyError("Episode not found")
        return e

    def reveal(self, eid, typed=False):
        with self.db.transaction() as c:
            self.expire(c)
            e = self.episode(c, eid)
            if not e["active"]:
                raise Conflict("Episode closed")
            run(
                c,
                "UPDATE episodes SET assisted=:assisted,status=:status WHERE id=:id",
                id=eid,
                assisted=int(typed),
                status="awaiting_answer" if typed else "awaiting_rating",
            )
            reference = row(c, "SELECT definition FROM revisions WHERE id=:id", id=e["revision_id"])
            if typed:
                self.apply_rating(c, eid, 1, e["expected_version"], "show")
            return reference

    def skip(self, eid):
        with self.db.transaction() as c:
            e = self.episode(c, eid)
            if e["active"]:
                local_date = (
                    self.clock()
                    .astimezone(ZoneInfo(self.settings(c)["timezone"]))
                    .date()
                    .isoformat()
                )
                run(
                    c,
                    "INSERT OR IGNORE INTO skips VALUES (:id,:date)",
                    id=e["card_id"],
                    date=local_date,
                )
                run(c, "UPDATE episodes SET active=0,status='skipped' WHERE id=:id", id=eid)
            elif e["status"] == "probe_pending":
                run(c, "UPDATE episodes SET status='closed' WHERE id=:id", id=eid)
            pending = row(
                c,
                "SELECT id FROM episodes WHERE session_id=:sid AND status='probe_pending' ORDER BY ordinal LIMIT 1",
                sid=e["session_id"],
            )
            run(
                c,
                "UPDATE sessions SET pending_probe_id=:pending WHERE id=:id",
                pending=pending["id"] if pending else None,
                id=e["session_id"],
            )
        return {"status": "skipped"}

    def idempotent(self, c, key, payload, operation):
        fingerprint = hashlib.sha256(dump(payload).encode()).hexdigest()
        old = row(c, "SELECT * FROM requests WHERE key=:key", key=key)
        if old:
            if old["fingerprint"] != fingerprint:
                raise Conflict("Idempotency key reused for different input")
            return json.loads(old["result"])
        result = operation()
        run(
            c,
            "INSERT INTO requests VALUES (:key,:fp,:result)",
            key=key,
            fp=fingerprint,
            result=dump(result),
        )
        return result

    def rate(self, eid, data):
        with self.db.transaction() as c:
            self.expire(c)
            return self.idempotent(
                c,
                data.request_key,
                [eid, data.model_dump()],
                lambda: self.apply_rating(c, eid, data.rating, data.expected_version, "manual"),
            )

    def apply_rating(self, c, eid, rating, expected_version, source):
        existing = row(c, "SELECT * FROM reviews WHERE episode_id=:id", id=eid)
        if existing:
            return existing
        e = self.episode(c, eid)
        state = row(c, "SELECT * FROM states WHERE card_id=:id", id=e["card_id"])
        card = self.get(e["card_id"], c)
        if not e["active"] or card["archived_at"] or card["revision_id"] != e["revision_id"]:
            raise Conflict("Episode closed or reference superseded")
        if state["version"] != expected_version or e["expected_version"] != expected_version:
            raise Conflict("Stale card state")
        config_id = self.config(c)
        scheduler = Scheduler.from_json(
            run(c, "SELECT data FROM scheduler_configs WHERE id=:id", id=config_id).scalar_one()
        )
        effective = 1 if e["assisted"] else rating
        review_time = self.clock()
        updated, _ = scheduler.review_card(
            Card.from_json(state["data"]), Rating(effective), review_datetime=review_time
        )
        rid = uid()
        run(
            c,
            "INSERT INTO reviews VALUES (:id,:episode,:card,:rating,:source,:now,:cfg,:before,:after,:version)",
            id=rid,
            episode=eid,
            card=e["card_id"],
            rating=effective,
            source=source,
            now=stamp(review_time),
            cfg=config_id,
            before=state["data"],
            after=updated.to_json(),
            version=state["version"] + 1,
        )
        run(
            c,
            "UPDATE states SET data=:data,due_at=:due,version=version+1,config_id=:cfg WHERE card_id=:id",
            data=updated.to_json(),
            due=stamp(updated.due),
            cfg=config_id,
            id=e["card_id"],
        )
        run(c, "UPDATE episodes SET active=0,status='graded' WHERE id=:id", id=eid)
        return row(c, "SELECT * FROM reviews WHERE id=:id", id=rid)

    def correct(self, rid, data):
        with self.db.transaction() as c:

            def operation():
                old = row(c, "SELECT * FROM reviews WHERE id=:id", id=rid)
                if not old:
                    raise KeyError("Review not found")
                state = row(c, "SELECT * FROM states WHERE card_id=:id", id=old["card_id"])
                if (
                    old["state_version"] != state["version"]
                    or data.expected_version != state["version"]
                ):
                    raise Conflict("Only the latest unchanged review can be corrected")
                scheduler = Scheduler.from_json(
                    run(
                        c, "SELECT data FROM scheduler_configs WHERE id=:id", id=old["config_id"]
                    ).scalar_one()
                )
                updated, _ = scheduler.review_card(
                    Card.from_json(old["before_state"]),
                    Rating(data.rating),
                    review_datetime=datetime.fromisoformat(old["reviewed_at"]),
                )
                run(
                    c,
                    "UPDATE states SET data=:data,due_at=:due,version=version+1 WHERE card_id=:id",
                    data=updated.to_json(),
                    due=stamp(updated.due),
                    id=old["card_id"],
                )
                run(
                    c,
                    "UPDATE reviews SET rating=:rating,after_state=:data,state_version=state_version+1 WHERE id=:id",
                    rating=data.rating,
                    data=updated.to_json(),
                    id=rid,
                )
                run(
                    c,
                    "UPDATE episodes SET active=0,status='cancelled' WHERE card_id=:id AND active=1",
                    id=old["card_id"],
                )
                result = row(c, "SELECT * FROM reviews WHERE id=:id", id=rid)
                self.audit(c, rid, "correction", data.reason, old, result)
                return result

            return self.idempotent(c, data.request_key, [rid, data.model_dump()], operation)

    def history(self):
        with self.db.engine.connect() as c:
            return rows(
                c,
                """SELECT v.*,r.term,r.definition,e.assisted,a.answer AS initial_answer,a.result AS assessment FROM reviews v JOIN episodes e ON e.id=v.episode_id LEFT JOIN attempts a ON a.episode_id=e.id AND a.kind='initial'
                JOIN revisions r ON r.id=e.revision_id ORDER BY v.reviewed_at DESC,v.id""",
            )
