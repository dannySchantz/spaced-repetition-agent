import asyncio
import json
from uuid import uuid4

from rich.text import Text
from textual import events, on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.reactive import reactive
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Select,
    Static,
    Switch,
    TabbedContent,
    TabPane,
    TextArea,
)

from .client import Client


class Flashcard(Static):
    """A compact terminal card with a horizontal flip illusion."""

    fraction = reactive(1.0)
    content_text = reactive("Start a review from Today.")

    def render(self):
        width = max(1, self.size.width - 4)
        shown = max(1, int(width * self.fraction))
        lines = Text(self.content_text).wrap(self.app.console, width)
        result = Text()
        for index, line in enumerate(lines):
            if index:
                result.append("\n")
            line.truncate(shown, overflow="crop")
            result.append(line)
        return result

    async def flip(self, content, reduced_motion):
        if not reduced_motion:
            self.animate("fraction", 0.02, duration=0.14)
            await asyncio.sleep(0.15)
        self.content_text = content
        if not reduced_motion:
            self.animate("fraction", 1.0, duration=0.14)
            await asyncio.sleep(0.15)
        else:
            self.fraction = 1.0


class RecallApp(App):
    TITLE = "Recall"
    CSS = """
    Screen { background: #101c29; }
    Header { background: #183347; }
    TabbedContent { height: 1fr; }
    TabbedContent > Tabs { display: none; }
    ContentSwitcher { height: 1fr; }
    TabPane { padding: 0 1; height: 1fr; }
    .row { height: 3; }
    Button { min-width: 10; margin-right: 1; }
    #connection, #progress, #feedback { height: auto; max-height: 3; }
    #card-scroll { height: 1fr; min-height: 5; border: round #4a91a0; }
    Flashcard { height: 7; min-height: 5; width: 72%; margin: 1 0; padding: 1 2; text-align: center; border: heavy #72c7d4; }
    #answer { height: 3; }
    #definition, #edit-definition, #rubric { height: 5; }
    DataTable { height: 1fr; min-height: 4; }
    .settings-label { width: 22; padding-top: 1; }
    #today-stats { margin: 1; height: auto; }
    #history-detail { height: auto; max-height: 5; }
    """
    BINDINGS = [("q", "quit", "Quit"), ("space", "reveal", "Reveal"), ("escape", "today", "Today")]

    def __init__(self, client=None):
        super().__init__()
        self.api = client or Client()
        self.session = None
        self.current = None
        self.revealed = False
        self.busy = False
        self.settings = {}
        self.cards = []
        self.reviews = []
        self.selected_card = None
        self.selected_review = None
        self.pending_probe = False
        self.front_text = "Start a review from Today."

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Connecting…", id="connection", markup=False)
        with TabbedContent(id="tabs"):
            with TabPane("Today", id="today"):
                yield Static("", id="today-stats", markup=False)
                yield Button("Start review", id="start-today", variant="primary")
                yield Button("Continue phone session", id="continue-phone")
                yield Button("Refresh", id="refresh")
            with TabPane("Collection", id="collection"):
                yield Input(placeholder="Search terms, context, or tags", id="search")
                yield DataTable(id="cards", cursor_type="row")
                with VerticalScroll():
                    yield Input(placeholder="Term", id="term")
                    yield TextArea(id="definition")
                    yield Input(placeholder="Context", id="context")
                    yield Input(placeholder="Optional concise SMS label", id="sms-label")
                    yield Input(placeholder="Tags, separated by commas", id="tags")
                    yield Label("Essential points (one per line; optional)")
                    yield TextArea(id="rubric")
                    with Horizontal(classes="row"):
                        yield Button("Add", id="add")
                        yield Button("Save edit", id="edit")
                        yield Button("Archive", id="archive")
                        yield Button("Restore", id="restore-card")
                    yield Label("Substantive edit: restart learning")
                    yield Switch(False, id="reset-learning")
                    yield Input(placeholder="Export destination (local file)", id="export-path")
                    yield Button("Export Markdown", id="export")
                    yield Input(
                        placeholder="Import path (.csv or term :: definition text)",
                        id="import-path",
                    )
                    yield Button("Import", id="import")
            with TabPane("Study", id="study"):
                yield Static("Ready", id="progress", markup=False)
                yield Button("Start review", id="start", variant="primary")
                with VerticalScroll(id="card-scroll"):
                    yield Flashcard(id="flashcard", markup=False)
                yield Input(placeholder="Type an answer (typed mode)", id="answer")
                with Horizontal(classes="row"):
                    yield Select(
                        [("Self-rate", "manual"), ("Type & grade", "typed")],
                        value="manual",
                        allow_blank=False,
                        id="mode",
                    )
                    yield Button("Submit", id="submit")
                    yield Button("Reveal", id="reveal")
                    yield Button("Skip", id="skip")
                with Horizontal(classes="row", id="ratings"):
                    for n, label in enumerate(["Again", "Hard", "Good", "Easy"], 1):
                        yield Button(f"{n} {label}", id=f"rate-{n}")
                yield Static("", id="feedback", markup=False)
                yield Static(
                    "Ask me to add cards, change your schedule, search, explain, archive or export.",
                    id="study-assistant-output",
                    markup=False,
                )
                yield Input(
                    placeholder="Tell Recall what you want… (Enter to send)",
                    id="study-assistant-input",
                )
                yield Button("Ask Recall", id="study-ask", variant="primary")
            with TabPane("Assistant", id="assistant"):
                with VerticalScroll():
                    yield Static(
                        "Offline assistant: add eigenvector; add term :: definition; search kernel; archive CARD_ID. Select cards in Collection for explanations.",
                        id="assistant-output",
                        markup=False,
                    )
                    yield Input(
                        placeholder="Ask to add, find, explain, compare or export",
                        id="assistant-input",
                    )
                    yield Button("Ask", id="ask")
                    yield Input(
                        placeholder="Draft card ID to approve (review the proposal above)",
                        id="approve-id",
                    )
                    yield Button("Approve draft", id="approve")
                    yield Label("Proposed edit: restart learning")
                    yield Switch(False, id="edit-reset")
                    yield Button("Approve displayed edit", id="approve-edit")
            with TabPane("History", id="history"):
                yield DataTable(id="reviews", cursor_type="row")
                yield Static(
                    "Select a review to inspect its original answer and schedule.",
                    id="history-detail",
                    markup=False,
                )
                with Horizontal(classes="row"):
                    yield Input(placeholder="Correction reason", id="correction-reason")
                    yield Select(
                        [(x, n) for n, x in enumerate(["Again", "Hard", "Good", "Easy"], 1)],
                        value=3,
                        allow_blank=False,
                        id="correction-rating",
                    )
                    yield Button("Correct latest", id="correct")
            with TabPane("Settings", id="settings"):
                with VerticalScroll():
                    yield Label("Reduced motion")
                    yield Switch(False, id="motion")
                    for key, label in [
                        ("timezone", "Timezone (e.g. America/New_York)"),
                        ("slots", "Review slots, separated by commas"),
                        ("quiet_start", "Quiet hours start (HH:MM)"),
                        ("quiet_end", "Quiet hours end (HH:MM)"),
                        ("batch_size", "Terms per SMS batch"),
                        ("new_per_day", "New terms per day"),
                        ("daily_prompts", "Initial SMS prompts per day"),
                        ("monthly_segments", "Monthly outbound segment allowance"),
                        ("retention", "FSRS desired retention (0.70–0.99)"),
                    ]:
                        yield Label(label)
                        yield Input(id="setting-" + key)
                    yield Label("Pause scheduled SMS")
                    yield Switch(True, id="sms-paused")
                    yield Label(
                        "I consent to SMS on the configured transport (START is required after STOP)"
                    )
                    yield Switch(False, id="sms-consent")
                    yield Button("Save settings", id="save-settings")
                    yield Static("", id="diagnostics", markup=False)
        yield Footer()

    async def on_mount(self):
        self.query_one("#cards", DataTable).add_columns("Term", "Context", "Status")
        self.query_one("#reviews", DataTable).add_columns("Term", "Rating", "Reviewed (UTC)")
        self.query_one("#ratings").visible = False
        self.query_one("#answer").display = False
        self.query_one("#submit").display = False
        await self.refresh_data()
        self.query_one("#tabs", TabbedContent).active = "study"
        if not self.settings.get("onboarding_complete", False):
            self.query_one("#study-assistant-output", Static).update(
                "Welcome to Recall. Tell me when you usually sleep, wake up, and when messages are welcome; I’ll choose the exact review times."
            )

    async def on_unmount(self):
        await self.api.close()

    async def call(self, method, path, **kwargs):
        try:
            return await self.api.request(method, path, **kwargs)
        except Exception as exc:
            self.notify(str(exc), severity="error", timeout=8)
            return None

    async def refresh_data(self):
        health = await self.call("GET", "health")
        if health is None:
            self.query_one("#connection", Static).update(
                f"Disconnected — start recall serve. Server: {self.api.url}"
            )
            return
        self.query_one("#connection", Static).update(
            f"Connected {self.api.url} • {health['database']}"
        )
        self.settings = await self.call("GET", "settings") or {}
        self.query_one("#motion", Switch).value = self.settings.get("reduced_motion", False)
        for key in [
            "timezone",
            "slots",
            "quiet_start",
            "quiet_end",
            "batch_size",
            "new_per_day",
            "daily_prompts",
            "monthly_segments",
            "retention",
        ]:
            value = self.settings.get(key, "")
            self.query_one("#setting-" + key, Input).value = (
                ", ".join(value) if isinstance(value, list) else str(value)
            )
        self.query_one("#sms-paused", Switch).value = self.settings.get("paused", True)
        self.query_one("#sms-consent", Switch).value = self.settings.get("opted_in", False)
        due = await self.call("GET", "due") or []
        self.reviews = await self.call("GET", "history") or []
        self.query_one("#today-stats", Static).update(
            f"Due now: {len(due)} • New: {sum(e['first_presented'] is None for e in due)}\nReviews recorded: {len(self.reviews)}\nSMS {'paused' if self.settings.get('paused', True) else 'enabled'} • Slots {', '.join(self.settings.get('slots', []))} ({self.settings.get('timezone', '')})"
        )
        diagnostics = await self.call("GET", "diagnostics") or health
        self.query_one("#diagnostics", Static).update(
            f"Transport: {diagnostics.get('adapter', 'unknown')}\nNext SMS: {diagnostics.get('next_delivery_at') or 'paused/no eligible slot'}\nEstimated outbound segments: {diagnostics.get('estimated_segments', 0)}\nAI tokens used/reserved: {diagnostics.get('ai_tokens', 0)}\nDatabase: {health['database']}"
        )
        table = self.query_one("#reviews", DataTable)
        table.clear()
        for r in self.reviews:
            table.add_row(Text(r["term"]), str(r["rating"]), r["reviewed_at"], key=r["id"])
        await self.search_cards()

    async def search_cards(self):
        self.cards = (
            await self.call(
                "GET",
                "cards",
                params={"q": self.query_one("#search", Input).value, "archived": True},
            )
            or []
        )
        table = self.query_one("#cards", DataTable)
        table.clear()
        for c in self.cards:
            table.add_row(
                Text(c["term"]),
                Text(c["context"]),
                "Archived" if c["archived_at"] else ("Approved" if c["approved"] else "Draft"),
                key=c["id"],
            )

    @on(Input.Changed, "#search")
    async def search_changed(self):
        if self.is_mounted:
            await self.search_cards()

    @on(DataTable.RowSelected, "#cards")
    def select_card(self, event):
        self.selected_card = next(c for c in self.cards if c["id"] == event.row_key.value)
        self.query_one("#term", Input).value = self.selected_card["term"]
        self.query_one("#definition", TextArea).load_text(self.selected_card["definition"])
        self.query_one("#context", Input).value = self.selected_card["context"]
        self.query_one("#sms-label", Input).value = self.selected_card.get("sms_label") or ""
        self.query_one("#tags", Input).value = ", ".join(self.selected_card["tags"])
        self.query_one("#rubric", TextArea).load_text("\n".join(self.selected_card["rubric"]))

    @on(DataTable.RowSelected, "#reviews")
    def select_review(self, event):
        self.selected_review = next(r for r in self.reviews if r["id"] == event.row_key.value)
        r = self.selected_review
        self.query_one("#history-detail", Static).update(
            f"{r['term']} — {r.get('initial_answer', 'Self-rated')}\nAssisted: {bool(r['assisted'])} • Next due: {json.loads(r['after_state'])['due']}\nOnly the latest review can be corrected."
        )

    async def start_review(self):
        if not self.session:
            sessions = await self.call("GET", "sessions") or []
            self.session = next(
                (
                    s
                    for s in sessions
                    if s["channel"] == "tui"
                    and any(e["active"] or e["status"] == "probe_pending" for e in s["episodes"])
                ),
                None,
            )
        if self.session:
            self.session = await self.call("GET", f"sessions/{self.session['id']}")
        if not self.session or not any(
            e["active"] or e["status"] == "probe_pending" for e in self.session["episodes"]
        ):
            self.session = await self.call("POST", "sessions", json={"request_key": str(uuid4())})
        self.query_one("#tabs", TabbedContent).active = "study"
        await self.next_card()

    async def next_card(self):
        self.revealed = False
        self.pending_probe = False
        self.query_one("#mode", Select).disabled = False
        self.query_one("#ratings").visible = False
        self.query_one("#answer", Input).value = ""
        self.query_one("#feedback", Static).update("")
        pending = [
            e
            for e in (self.session or {}).get("episodes", [])
            if e["active"] or e["status"] == "probe_pending"
        ]
        self.current = pending[0] if pending else None
        if self.current:
            self.front_text = self.current["term"] + (
                "\n" + self.current["context"] if self.current["context"] else ""
            )
            self.query_one("#flashcard", Flashcard).content_text = self.front_text
            self.query_one("#progress", Static).update(
                f"Card {self.current['ordinal']} of {len(self.session['episodes'])}"
            )
            self.query_one("#reveal", Button).focus()
            if self.current["status"] == "probe_pending":
                attempts = await self.call("GET", f"episodes/{self.current['id']}/attempts") or []
                initial = next((a for a in attempts if a["kind"] == "initial"), None)
                if initial and initial.get("result") and initial["result"].get("probe"):
                    self.pending_probe = True
                    self.query_one("#mode", Select).value = "typed"
                    self.query_one("#mode", Select).disabled = True
                    self.query_one("#answer").display = True
                    self.query_one("#submit").display = True
                    self.query_one("#flashcard", Flashcard).content_text = initial["result"][
                        "probe"
                    ]
                    self.query_one("#feedback", Static).update(
                        "Wrong on first attempt. This follow-up preserves that rating."
                    )
                    self.query_one("#answer", Input).focus()
        else:
            self.query_one(
                "#flashcard", Flashcard
            ).content_text = "Session complete. Return to Today for newly due cards."
            self.query_one("#progress", Static).update("Complete")
            await self.refresh_data()

    async def action_reveal(self):
        if (
            self.query_one("#tabs", TabbedContent).active != "study"
            or isinstance(self.focused, (Input, TextArea))
            or self.busy
        ):
            return
        await self.reveal()

    async def reveal(self):
        if not self.current or self.busy:
            return
        if self.revealed:
            await self.unreveal()
            return
        self.busy = True
        try:
            typed = self.query_one("#mode", Select).value == "typed"
            self.query_one("#mode", Select).disabled = True
            value = await self.call(
                "POST", f"episodes/{self.current['id']}/reveal", params={"typed": typed}
            )
            if value is None:
                return
            await self.query_one("#flashcard", Flashcard).flip(
                value["definition"], self.settings.get("reduced_motion", False)
            )
            self.revealed = True
            self.query_one("#ratings").visible = not typed
            if typed:
                self.query_one("#feedback", Static).update(
                    "Assisted reveal recorded as Again. Skip to continue."
                )
        finally:
            self.busy = False

    async def unreveal(self):
        if not self.current or self.busy:
            return
        self.busy = True
        try:
            await self.query_one("#flashcard", Flashcard).flip(
                self.front_text, self.settings.get("reduced_motion", False)
            )
            self.revealed = False
            self.query_one("#ratings").visible = False
            if not self.pending_probe:
                self.query_one("#mode", Select).disabled = False
        finally:
            self.busy = False

    async def rate(self, n):
        if (
            self.busy
            or not self.current
            or not self.revealed
            or self.query_one("#mode", Select).value != "manual"
        ):
            return
        self.busy = True
        try:
            result = await self.call(
                "POST",
                f"episodes/{self.current['id']}/rating",
                json={
                    "rating": n,
                    "expected_version": self.current["expected_version"],
                    "request_key": str(uuid4()),
                },
            )
            if result is not None:
                self.current["active"] = 0
                self.current["status"] = "closed"
                await self.next_card()
        finally:
            self.busy = False

    async def on_key(self, event: events.Key):
        if (
            event.key in {"1", "2", "3", "4"}
            and not isinstance(self.focused, (Input, TextArea, Select))
            and self.query_one("#tabs", TabbedContent).active == "study"
        ):
            event.stop()
            await self.rate(int(event.key))

    def action_today(self):
        self.query_one("#tabs", TabbedContent).active = "today"

    @on(Select.Changed, "#mode")
    def mode_changed(self, event):
        typed = event.value == "typed"
        self.query_one("#answer").display = typed
        self.query_one("#submit").display = typed
        self.query_one("#ratings").visible = self.revealed and not typed
        if typed:
            self.query_one("#answer", Input).focus()

    @on(Input.Submitted, "#answer")
    async def submit_answer(self):
        await self.typed_answer()

    async def typed_answer(self):
        if self.busy or not self.current or self.revealed:
            return
        answer = self.query_one("#answer", Input).value.strip()
        if not answer:
            return
        self.busy = True
        self.query_one("#mode", Select).disabled = True
        try:
            result = await self.call(
                "POST",
                f"episodes/{self.current['id']}/attempts",
                json={
                    "answer": answer,
                    "request_key": str(uuid4()),
                    "kind": "probe" if self.pending_probe else "initial",
                },
            )
            if not result:
                return
            grade = result.get("result")
            if not grade or grade["verdict"] == "ungraded":
                self.query_one("#feedback", Static).update(
                    "Pending — switch to Self-rate, reveal, and choose your rating."
                )
                self.query_one("#mode", Select).disabled = False
                return
            label = "Right" if grade["verdict"] == "right" else "Wrong"
            if self.pending_probe:
                label += (
                    " after hint" if grade["verdict"] == "right" else " after hint; see reference"
                )
            self.query_one("#feedback", Static).update(
                label
                + (
                    " — " + grade["probe"]
                    if grade.get("probe")
                    else " — " + (grade.get("correction") or "Use Skip to continue.")
                )
            )
            self.query_one("#answer", Input).value = ""
            if grade.get("probe"):
                self.pending_probe = True
                self.query_one("#flashcard", Flashcard).content_text = grade["probe"]
            else:
                self.revealed = True
        finally:
            self.busy = False

    @on(Button.Pressed)
    async def button(self, event):
        ident = event.button.id
        if ident in {"start", "start-today"}:
            await self.start_review()
        elif ident == "refresh":
            await self.refresh_data()
        elif ident == "reveal":
            await self.reveal()
        elif ident == "submit":
            await self.typed_answer()
        elif ident == "skip" and self.current and not self.busy:
            if await self.call("POST", f"episodes/{self.current['id']}/skip") is not None:
                self.current["active"] = 0
                self.current["status"] = "closed"
                await self.next_card()
        elif ident and ident.startswith("rate-"):
            await self.rate(int(ident[-1]))
        elif ident in {"add", "edit"}:
            data = {
                "term": self.query_one("#term", Input).value,
                "definition": self.query_one("#definition", TextArea).text,
                "context": self.query_one("#context", Input).value,
                "sms_label": self.query_one("#sms-label", Input).value or None,
                "tags": [
                    v.strip() for v in self.query_one("#tags", Input).value.split(",") if v.strip()
                ],
                "rubric": [
                    v.strip()
                    for v in self.query_one("#rubric", TextArea).text.splitlines()
                    if v.strip()
                ],
            }
            if ident == "edit":
                if not self.selected_card:
                    self.notify("Select a card first")
                    return
                data.update(
                    expected_revision=self.selected_card["revision_id"],
                    reset_learning=self.query_one("#reset-learning", Switch).value,
                    approved=bool(self.selected_card["approved"]),
                )
            result = await self.call(
                "POST" if ident == "add" else "PATCH",
                "cards" if ident == "add" else f"cards/{self.selected_card['id']}",
                json=data,
            )
            if result:
                self.selected_card = result
                await self.refresh_data()
        elif ident in {"archive", "restore-card"} and self.selected_card:
            await self.call(
                "POST",
                f"cards/{self.selected_card['id']}/{'archive' if ident == 'archive' else 'restore'}",
            )
            await self.refresh_data()
        elif ident == "save-settings":
            try:
                data = dict(self.settings)
                for key in ["timezone", "quiet_start", "quiet_end"]:
                    data[key] = self.query_one("#setting-" + key, Input).value.strip()
                data["slots"] = [
                    s.strip()
                    for s in self.query_one("#setting-slots", Input).value.split(",")
                    if s.strip()
                ]
                for key in ["batch_size", "new_per_day", "daily_prompts", "monthly_segments"]:
                    data[key] = int(self.query_one("#setting-" + key, Input).value)
                data["retention"] = float(self.query_one("#setting-retention", Input).value)
                data["paused"] = self.query_one("#sms-paused", Switch).value
                data["opted_in"] = self.query_one("#sms-consent", Switch).value
                data["reduced_motion"] = self.query_one("#motion", Switch).value
                await self.call("PUT", "settings", json=data)
                await self.refresh_data()
            except ValueError as exc:
                self.notify(str(exc), severity="error")
        elif ident == "correct" and self.selected_review:
            r = self.selected_review
            await self.call(
                "POST",
                f"reviews/{r['id']}/correction",
                json={
                    "rating": self.query_one("#correction-rating", Select).value,
                    "expected_version": r["state_version"],
                    "request_key": str(uuid4()),
                    "reason": self.query_one("#correction-reason", Input).value,
                },
            )
            await self.refresh_data()
        elif ident in {"export", "import"}:
            from pathlib import Path

            try:
                if ident == "export":
                    value = await self.call("GET", "export", params={"format": "markdown"})
                    if value:
                        with (
                            Path(self.query_one("#export-path", Input).value)
                            .expanduser()
                            .open("x") as output
                        ):
                            output.write(value["content"])
                        self.notify("Export saved")
                else:
                    path = Path(self.query_one("#import-path", Input).value).expanduser()
                    await self.call(
                        "POST",
                        "import",
                        json={
                            "content": path.read_text(),
                            "format": "csv" if path.suffix == ".csv" else "lines",
                        },
                    )
                    await self.refresh_data()
            except (OSError, ValueError) as exc:
                self.notify(str(exc), severity="error")
        elif ident == "ask":
            await self.submit_assistant("#assistant-input", "#assistant-output")
        elif ident == "study-ask":
            await self.submit_assistant("#study-assistant-input", "#study-assistant-output")
        elif ident == "approve":
            cid = self.query_one("#approve-id", Input).value.strip()
            draft = next((c for c in getattr(self, "assistant_drafts", []) if c["id"] == cid), None)
            if not draft:
                self.notify("Use an ID from the displayed draft proposals")
                return
            result = await self.call(
                "POST", f"cards/{cid}/approve", json={"expected_revision": draft["revision_id"]}
            )
            if result:
                self.notify("Draft approved")
                await self.refresh_data()
        elif ident == "approve-edit":
            proposal = getattr(self, "assistant_edit", None)
            if not proposal:
                self.notify("Ask for an edit proposal first: edit CARD_ID :: definition")
                return
            result = await self.call(
                "POST",
                f"assistant/edits/{proposal['id']}/approve",
                json={"reset_learning": self.query_one("#edit-reset", Switch).value},
            )
            if result:
                self.notify("Edit approved")
                self.assistant_edit = None
                await self.refresh_data()
        elif ident == "continue-phone":
            sessions = await self.call("GET", "sessions") or []
            phone = next((s for s in sessions if s["channel"] == "sms"), None)
            if phone:
                self.session = phone
                self.query_one("#tabs", TabbedContent).active = "study"
                await self.next_card()
            else:
                self.notify("No active phone session.")

    @on(Input.Submitted, "#assistant-input")
    async def ask_assistant(self):
        await self.submit_assistant("#assistant-input", "#assistant-output")

    @on(Input.Submitted, "#study-assistant-input")
    async def ask_study_assistant(self):
        await self.submit_assistant("#study-assistant-input", "#study-assistant-output")

    async def submit_assistant(self, input_id, output_id):
        selected = [self.selected_card["id"]] if self.selected_card else []
        text = self.query_one(input_id, Input).value.strip()
        if not text:
            return
        value = await self.call(
            "POST",
            "assistant",
            json={
                "message": text,
                "selected_ids": selected,
            },
        )
        if value:
            self.assistant_drafts = value.get("drafts", [])
            display = value.get("message", "")
            self.assistant_edit = value.get("edit_proposal")
            if self.assistant_edit:
                p = self.assistant_edit
                display += f"\n\nProposed edit: {p['term']} ({p['context']})\n{p['definition']}\nCard: {p['card_id']}"
            for c in value.get("cards", []) + self.assistant_drafts:
                display += f"\n\n{c['term']} ({c['context']})\n{c['definition']}\nID: {c['id']}"
                if c["rubric"]:
                    display += "\nEssential points: " + "; ".join(c["rubric"])
            if value.get("content"):
                display += "\n\n" + value["content"]
            self.query_one(output_id, Static).update(display)
            self.query_one(input_id, Input).value = ""
            await self.refresh_data()
