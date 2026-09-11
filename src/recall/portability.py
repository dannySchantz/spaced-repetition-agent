"""Explicit exports; learning imports never restore delivery queues or consent."""

import csv
import io
import json
import sqlite3
import tempfile
from pathlib import Path

from .core import dump, rows, run
from .domain import CardInput, Settings

TABLES = [
    "settings",
    "cards",
    "revisions",
    "scheduler_configs",
    "states",
    "sessions",
    "episodes",
    "reviews",
    "audit",
    "requests",
    "skips",
    "attempts",
]


def export_learning(core):
    with core.db.read_transaction() as c:
        result = {
            "format": "recall-learning",
            "version": 1,
            "tables": {t: rows(c, f"SELECT * FROM {t}") for t in TABLES},
        }
    result["tables"]["settings"][0]["data"] = dump(
        {
            **Settings.model_validate_json(result["tables"]["settings"][0]["data"]).model_dump(),
            "paused": True,
            "opted_in": False,
        }
    )
    return result


def import_learning(core, value):
    if (
        value.get("format") != "recall-learning"
        or value.get("version") != 1
        or set(value.get("tables", {})) != set(TABLES)
    ):
        raise ValueError("Unsupported learning backup")
    tables = value["tables"]
    settings = Settings.model_validate(json.loads(tables["settings"][0]["data"])).model_dump()
    settings.update(paused=True, opted_in=False)
    with core.db.transaction() as c:
        if run(c, "SELECT COUNT(*) FROM cards").scalar_one():
            raise ValueError("Learning-data restore requires an empty collection")
        run(c, "DELETE FROM settings")
        for table in TABLES:
            allowed = {r["name"] for r in rows(c, f"PRAGMA table_info({table})")}
            for item in tables[table]:
                if set(item) != allowed:
                    raise ValueError(f"Invalid columns in {table}")
                names = list(item)
                run(
                    c,
                    f"INSERT INTO {table} ({','.join(names)}) VALUES ({','.join(':' + n for n in names)})",
                    **item,
                )
        run(c, "UPDATE settings SET data=:data WHERE id=1", data=dump(settings))
        run(
            c,
            "UPDATE sessions SET status='cancelled' WHERE status NOT IN ('complete','expired','cancelled')",
        )
        run(c, "UPDATE episodes SET active=0,status='cancelled' WHERE active=1")
        if rows(c, "PRAGMA foreign_key_check"):
            raise ValueError("Broken references in learning backup")
    return {"imported": len(tables["cards"])}


def readable(core, format):
    cards = [c for c in core.collection() if c["approved"]]
    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["term", "definition", "context", "tags", "due_at"])
        for c in cards:
            writer.writerow(
                [c["term"], c["definition"], c["context"], "|".join(c["tags"]), c["due_at"]]
            )
        return output.getvalue()

    def escape(s):
        return s.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")

    return (
        "# Recall collection\n\n| Term | Definition | Context | Tags | Next due (UTC) |\n|---|---|---|---|---|\n"
        + "".join(
            "| "
            + " | ".join(
                escape(str(v))
                for v in [
                    c["term"],
                    c["definition"],
                    c["context"],
                    ", ".join(c["tags"]),
                    c["due_at"],
                ]
            )
            + " |\n"
            for c in cards
        )
    )


def import_cards(core, content, format):
    if format == "csv":
        parsed = [
            CardInput(
                term=r["term"],
                definition=r["definition"],
                context=r.get("context", ""),
                tags=r.get("tags", "").split("|") if r.get("tags") else [],
            )
            for r in csv.DictReader(io.StringIO(content))
        ]
    else:
        parsed = []
        for line in content.splitlines():
            if line.strip():
                term, separator, definition = line.partition("::")
                if not separator:
                    raise ValueError("Each line must be term :: definition")
                parsed.append(CardInput(term=term, definition=definition))
    with core.db.transaction() as c:
        return [core.add(v, c) for v in parsed]


def snapshot(core):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "snapshot.db"
        with sqlite3.connect(core.db.path) as source, sqlite3.connect(path) as target:
            source.backup(target)
        content = path.read_bytes()
        with core.db.transaction() as c:
            run(
                c,
                "INSERT INTO diagnostics VALUES ('last_backup',:now) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                now=core.now(),
            )
        return content


def restore_snapshot(core, content):
    """Service-owned restore, requiring an empty destination. Never replace a running database file."""
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "restore.db"
        path.write_bytes(content)
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as source:
            if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Invalid SQLite backup")
        from .storage import Database

        db = Database(path)
        db.migrate()
        try:
            full_tables = TABLES + [
                "edit_proposals",
                "inbox",
                "outbox",
                "dispatch_slots",
                "diagnostics",
                "ai_usage",
            ]
            with db.engine.connect() as conn:
                tables = {t: rows(conn, f"SELECT * FROM {t} ORDER BY rowid") for t in full_tables}
            core.db.local_snapshot()
            with core.db.transaction() as conn:
                if core.settings(conn)["opted_in"]:
                    raise ValueError("Opt out and pause destination delivery before restoring")
                if run(conn, "SELECT COUNT(*) FROM cards").scalar_one():
                    raise ValueError(
                        "Restore requires an empty destination; original remains unchanged"
                    )
                for table in reversed(full_tables):
                    run(conn, f"DELETE FROM {table}")
                for table in full_tables:
                    allowed = {r["name"] for r in rows(conn, f"PRAGMA table_info({table})")}
                    for item in tables[table]:
                        if set(item) != allowed:
                            raise ValueError("Unsupported snapshot columns")
                        names = list(item)
                        run(
                            conn,
                            f"INSERT INTO {table} ({','.join(names)}) VALUES ({','.join(':' + n for n in names)})",
                            **item,
                        )
                settings = core.settings(conn)
                settings.update(paused=True, opted_in=False)
                run(conn, "UPDATE settings SET data=:data WHERE id=1", data=dump(settings))
                run(
                    conn,
                    "UPDATE sessions SET status='cancelled' WHERE status NOT IN ('complete','expired','cancelled','delivery_failed')",
                )
                run(
                    conn,
                    "UPDATE episodes SET active=0,status='cancelled' WHERE active=1 OR status='probe_pending'",
                )
                run(
                    conn,
                    "UPDATE attempts SET status='manual_pending',lease_until=NULL,lease_token=NULL WHERE status IN ('pending','processing')",
                )
                run(
                    conn,
                    "UPDATE inbox SET status='cancelled' WHERE status IN ('pending','processing')",
                )
                run(
                    conn,
                    "UPDATE outbox SET status=CASE WHEN status='sending' THEN 'uncertain' ELSE 'cancelled' END,lease_until=NULL WHERE status IN ('sending','queued')",
                )
                run(conn, "UPDATE dispatch_slots SET reserved_segments=0")
                if rows(conn, "PRAGMA foreign_key_check"):
                    raise ValueError("Broken snapshot references")
                core.audit(
                    conn,
                    "database",
                    "restore",
                    "Restored with delivery paused and unfinished work reconciled",
                )
            return {"imported": len(tables["cards"]), "paused": True}
        finally:
            db.engine.dispose()
