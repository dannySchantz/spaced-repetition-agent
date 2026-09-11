"""Persist answers first, call provider without a write lock, apply once after revalidation."""

import json
from datetime import timedelta

from recall.core import Conflict, dump, row, rows, run, uid
from recall.domain import stamp

from .grader import PROMPT_VERSION, FixtureProvider, GradeBatch


class Grading:
    def __init__(self, core, provider=None):
        self.core = core
        self.provider = provider or FixtureProvider()
        self.on_failure = None
        self.on_result = None  # Application-owned transactional outbox hook, added by messaging.

    def submit(self, submissions, source_key):
        group_id = uid()
        ids = []
        with self.core.db.transaction() as c:
            self.core.expire(c)
            for index, submission in enumerate(submissions):
                eid, answer, kind = (
                    submission["episode_id"],
                    submission["answer"],
                    submission.get("kind", "initial"),
                )
                if not answer.strip() or len(answer) > 20000 or kind not in {"initial", "probe"}:
                    raise ValueError("Invalid answer")
                key = f"{source_key}:{index}"
                old = row(c, "SELECT * FROM attempts WHERE request_key=:key", key=key)
                if old:
                    if (old["episode_id"], old["answer"], old["kind"]) != (eid, answer, kind):
                        raise Conflict("Request key reused for another answer")
                    ids.append(old["id"])
                    continue
                old = row(
                    c,
                    "SELECT * FROM attempts WHERE episode_id=:eid AND kind=:kind",
                    eid=eid,
                    kind=kind,
                )
                if old:
                    ids.append(old["id"])
                    continue
                e = self.core.episode(c, eid)
                session = row(c, "SELECT status FROM sessions WHERE id=:id", id=e["session_id"])
                if session["status"] in {"expired", "cancelled", "complete"}:
                    raise Conflict("Session closed")
                if kind == "initial" and (
                    not e["active"] or row(c, "SELECT id FROM reviews WHERE episode_id=:id", id=eid)
                ):
                    raise Conflict("Episode already completed")
                if kind == "probe" and e["status"] != "probe_pending":
                    raise Conflict("No pending probe")
                aid = uid()
                run(
                    c,
                    """INSERT INTO attempts (id,episode_id,kind,answer,received_at,request_key,group_id,status)
                    VALUES (:id,:eid,:kind,:answer,:now,:key,:group,'pending')""",
                    id=aid,
                    eid=eid,
                    kind=kind,
                    answer=answer,
                    now=self.core.now(),
                    key=key,
                    group=group_id,
                )
                if kind == "initial":
                    run(c, "UPDATE episodes SET status='grading' WHERE id=:id", id=eid)
                ids.append(aid)
        return ids

    def get(self, ids):
        with self.core.db.engine.connect() as c:
            result = []
            for aid in ids:
                value = row(c, "SELECT * FROM attempts WHERE id=:id", id=aid)
                if value:
                    value["result"] = json.loads(value["result"]) if value["result"] else None
                    result.append(value)
            return result

    def process(self, group_id=None):
        core = self.core
        with core.db.transaction() as c:
            core.expire(c)
            run(
                c,
                "UPDATE attempts SET status='manual_pending',error='Retry lease exhausted',lease_until=NULL WHERE status='processing' AND tries>=2 AND lease_until<=:now",
                now=core.now(),
            )
            candidate = row(
                c,
                """SELECT group_id FROM attempts WHERE tries<2 AND (status='pending' OR
                (status='processing' AND lease_until<=:now)) AND (:group IS NULL OR group_id=:group)
                ORDER BY received_at LIMIT 1""",
                now=core.now(),
                group=group_id,
            )
            if not candidate:
                return False
            attempts = rows(
                c,
                """SELECT * FROM attempts WHERE group_id=:group AND tries<2 AND
                (status='pending' OR (status='processing' AND lease_until<=:now))""",
                group=candidate["group_id"],
                now=core.now(),
            )
            token = uid()
            items = []
            valid_attempts = []
            for a in attempts:
                e = core.episode(c, a["episode_id"])
                session = row(c, "SELECT status FROM sessions WHERE id=:id", id=e["session_id"])
                if (
                    session["status"] in {"expired", "cancelled", "complete"}
                    or (a["kind"] == "initial" and not e["active"])
                    or (a["kind"] == "probe" and e["status"] != "probe_pending")
                ):
                    run(c, "UPDATE attempts SET status='cancelled' WHERE id=:id", id=a["id"])
                    continue
                reference = row(c, "SELECT * FROM revisions WHERE id=:id", id=e["revision_id"])
                initial = row(
                    c,
                    "SELECT answer,result FROM attempts WHERE episode_id=:id AND kind='initial'",
                    id=e["id"],
                )
                items.append(
                    {
                        "episode_id": e["id"],
                        "term": reference["term"],
                        "reference": reference["definition"],
                        "context": reference["context"],
                        "rubric": json.loads(reference["rubric"]),
                        "revision_id": reference["id"],
                        "answer": a["answer"],
                        "kind": a["kind"],
                        "initial_answer": initial["answer"]
                        if a["kind"] == "probe" and initial
                        else None,
                        "probe": json.loads(initial["result"])["probe"]
                        if a["kind"] == "probe" and initial and initial["result"]
                        else None,
                    }
                )
                run(
                    c,
                    "UPDATE attempts SET status='processing',tries=tries+1,lease_until=:lease,lease_token=:token WHERE id=:id",
                    id=a["id"],
                    lease=stamp(core.clock() + timedelta(seconds=60)),
                    token=token,
                )
                valid_attempts.append(a)
        if not items:
            return True
        try:
            response = self.provider.grade(items)
            if len(dump(response.data)) > 100000:
                raise ValueError("Oversized grading response")
            batch = GradeBatch.model_validate(response.data).validate_ids(
                [i["episode_id"] for i in items]
            )
            for item, a in zip(items, valid_attempts, strict=True):
                grade = next(g for g in batch.results if g.episode_id == item["episode_id"])
                if a["kind"] == "probe" and grade.probe:
                    raise ValueError("A probe cannot request another probe")
        except Exception as exc:
            with core.db.transaction() as c:
                for a in valid_attempts:
                    run(
                        c,
                        "UPDATE attempts SET status=CASE WHEN tries>=2 THEN 'manual_pending' ELSE 'pending' END,error=:error,lease_until=NULL WHERE id=:id AND lease_token=:token",
                        id=a["id"],
                        token=token,
                        error=type(exc).__name__,
                    )
                if self.on_failure:
                    self.on_failure(c, valid_attempts)

            return True
        with core.db.transaction() as c:
            core.expire(c)
            completed = []
            for a in valid_attempts:
                current = row(c, "SELECT * FROM attempts WHERE id=:id", id=a["id"])
                if current["lease_token"] != token or current["status"] != "processing":
                    continue
                grade = next(g for g in batch.results if g.episode_id == a["episode_id"])
                e = core.episode(c, a["episode_id"])
                card = core.get(e["card_id"], c)
                session = row(c, "SELECT status FROM sessions WHERE id=:id", id=e["session_id"])
                stale = (
                    card["revision_id"] != e["revision_id"]
                    or card["archived_at"]
                    or session["status"] in {"expired", "cancelled", "complete"}
                )
                if a["kind"] == "initial":
                    stale = stale or not e["active"] or card["version"] != e["expected_version"]
                else:
                    stale = stale or e["status"] != "probe_pending"
                if stale:
                    run(
                        c,
                        "UPDATE attempts SET status='cancelled',lease_until=NULL WHERE id=:id",
                        id=a["id"],
                    )
                    continue
                if grade.verdict != "ungraded":
                    if a["kind"] == "initial":
                        core.apply_rating(
                            c,
                            e["id"],
                            3 if grade.verdict == "right" else 1,
                            e["expected_version"],
                            "typed",
                        )
                        if grade.probe:
                            run(
                                c,
                                "UPDATE episodes SET status='probe_pending' WHERE id=:id",
                                id=e["id"],
                            )
                    else:
                        run(c, "UPDATE episodes SET status='taught' WHERE id=:id", id=e["id"])
                run(
                    c,
                    """UPDATE attempts SET status=:status,result=:result,provider=:provider,model=:model,
                    prompt_version=:prompt,usage=:usage,error=NULL,lease_until=NULL WHERE id=:id""",
                    id=a["id"],
                    status="manual_pending" if grade.verdict == "ungraded" else "graded",
                    result=grade.model_dump_json(),
                    provider=response.provider,
                    model=response.model,
                    prompt=PROMPT_VERSION,
                    usage=dump(response.usage),
                )
                completed.append(
                    {
                        **a,
                        "result": grade.model_dump(),
                        "session_id": e["session_id"],
                        "ordinal": e["ordinal"],
                    }
                )
            if self.on_result and completed:
                self.on_result(c, completed)
        return True

    def drain(self):
        for _ in range(200):
            if not self.process():
                break
