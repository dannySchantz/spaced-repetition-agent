# Implementation status

Updated September 11, 2026. M0–M6 local acceptance gates passed. Current schema: 0007.
Final verification: **52 tests passed**, Ruff checks/format passed, dependency checks passed.
Clean non-editable install and isolated Linux container startup/restart drills passed.
See [acceptance evidence](acceptance.md) and [simulator transcript](simulator-transcript.md).

## M0 — complete
Implemented: separate `recall` Conda environment (Python 3.12.13), installable package,
Typer CLI, FastAPI service, Alembic migration, durable SQLite settings, dependency locks,
third-party license texts. Versions include FSRS 6.3.2, Textual 8.2.8, SQLAlchemy 2.0.52.
Verification: 2 tests passed; `pip check` passed; wheel installed in clean `/tmp/recall-clean-install`
venv from locked dependencies; `recall init` created schema 0001; running service answered
`recall doctor` with status ok. Initial migration bug caught and fixed before passing.
Commands: `conda activate recall`; `recall serve`; in another terminal `recall doctor`.
Known limitation: this machine needs curl for dependency downloads; see decisions.md.

## M1 — complete
Implemented: approved/draft cards, immutable revisions, search, line/CSV import,
JSON learning export/import and readable exports, FSRS scheduling, reservations,
manual ratings, request idempotency, audited latest-review correction, backup/restore.
Verification: 7 tests passed covering concurrent reservations/ratings, stale state/revisions,
expiry, same-session later due episode, restore, and failed import atomicity.
`python scripts/demo_manual.py` ran a real service, CLI add/reveal/Good review, and restart;
one review and exact FSRS state persisted. Backups restore only into empty collections,
with sessions cancelled and SMS paused.
Commands: `recall add kernel "Inputs mapped to zero"`; `recall review`; `recall backup snapshot.db`.

## M2 — complete (automated gate)
Implemented: Today, Collection, Study, History, Settings, API client, 220 ms collapse/expand
reveal, self-ratings, typed-input shell, import/export, corrections, reduced motion.
Verification: 5 headless TUI checks passed at 80×24 and 120×36, motion on/off,
long Unicode references, rapid reveal/rating, resize, and digits/spaces while typing.
Rendered compact study screenshot inspected; controls fit after fixing the scroll layout.
Screenshots: docs/screenshots/*.svg; regenerate with `python scripts/capture_tui.py`.
Commands: `recall serve`, then `recall` in another terminal.
Known limitation: physical-terminal animation smoothness still merits owner inspection;
headless behavior and rendered layouts are verified. No human pilot claimed.

## M3 — complete (offline gate)
Implemented: Responses API adapter, strict validated results and exact IDs, saved original
answers, bounded retry/leases, stale-result rejection, one-probe teaching, typed TUI flow.
Verification: 19 total tests passed. Timeout and malformed results stay pending after two
tries; reference edits during a provider call discard results; restart recovers pending
answers; successful probes preserve the original Wrong/Again review.
`python evals/run_grader_eval.py`: 63 fixture cases, 100% replay agreement, zero must-fail
false Right. This is contract verification, not evidence of live semantic accuracy.
Commands: evaluation command above; typed Study with the explicit bundled demo fixtures.
Known limitation: live evaluation, independent label/probe review and model selection await
spending authorization. Unknown offline answers stay pending for manual rating.

## M4 — complete (simulator gate)
Implemented: coded numbered replies, partial submissions, queued probes, administrative
commands, persistent inbox/outbox, duplicate suppression, send leases and uncertainty,
GSM/UTF-16 segment estimates, quiet hours/slots/DST, daily/new/monthly allowances,
shared TUI/SMS episodes and simulator commands.
Verification: 9 SMS tests passed; transcript demo graded three items before probing and
preserved first ratings. Verified stale codes/items, TUI completion, expiry, duplicate
callbacks, restart inbox recovery, no resend after uncertain acceptance, STOP before
queued grading, older START cancellation, DST folds/gaps, missed slots and daily limits.
Commands: `recall sms setup`; `recall sms simulate MORE`; reply using the displayed code.
`python scripts/demo_sms.py` writes docs/simulator-transcript.md without credentials.
Known limitation: live carrier behavior is unverified; M6 covers the adapter with mocks.

## M5 — complete (offline gate)
Implemented: separate bounded assistant provider, supplied-definition capture, immediate
assistant additions/edits, search, selected-reference explanations/comparisons, recoverable
archive/restore and export. Verification covers unselected model action rejection,
owner-intent checks, auto-applied bulk changes, immutable revisions, and grading/management
separation. Commands: `recall assistant "add eigenvector"`;
`recall assistant "add rank :: Dimension of the image"`; Assistant tab in `recall`.
Personal free-form model-backed assistance is enabled with the live API settings documented
in README; offline mode remains deterministic and fixture-backed.

## M6 — complete (local readiness gate)
Implemented: Twilio SDK adapter, canonical-URL signature verification, owner/account/sender
restrictions, provider opt-out handling, explicit live flags and allowances, evaluation-gated
AI provider, diagnostics, service process lock, pre-migration snapshots and safe restore,
Docker/Compose/Caddy package, exact live account and deployment runbooks.
Verification: final 52-test suite passed in 12.87 seconds; Ruff lint/format and `pip check`
passed. A clean non-editable Python 3.12 install passed CLI/service restart checks. Linux
arm64 image built from pinned dependencies; an isolated container passed authenticated
startup, add/rate, restart and exact-state persistence, plus `pip check`. Compose config and
Caddy validation passed. No ports were published during the container drill.
Twilio mocks verified invalid signatures/owner rejection, duplicate callbacks, STOP/START,
definitive rejection, uncertain acceptance, out-of-order statuses, and a delivered callback
arriving before the SDK send returned. Restore tests retained history/edit proposals and
cancelled stale queues. Fresh schema and upgrade-with-backup checks passed through 0007.
Final hardening: shared new-card limits, consistent JSON snapshots during concurrent writes,
restorable pending TUI probes, stationary controls during reveal, and explicit concise SMS labels.
Commands: `pytest -q`; `ruff check src tests scripts evals`; `python scripts/demo_manual.py`;
`docker build -f deploy/Dockerfile -t recall-local:verification .`; `python scripts/demo_container.py`.
Known limitation: this is an implemented adapter awaiting live verification, not a phone release.

## M7 — not started; live prerequisites and authorization required
Remaining: recipient country/type and sender registration, consenting phone setup, approved
SMS/hosting allowances, deployment authorization, real conversations/quiet-hour/opt-out tests,
and a week of observed personal use. Personal AI use can now be enabled with
`RECALL_ALLOW_UNEVALUATED_AI=true`; shared deployments should retain the evaluation gate.

Personal-use changes after M6: assistant additions and edits auto-apply, bulk archive/restore
no longer asks for a second confirmation, and code-less inbound SMS beginning with natural
language such as `add eigenvector to my spaced repetition` is routed to the assistant.
The TUI now opens to one study screen with the assistant below the flashcard. On first run,
the assistant asks for sleep/wake and acceptable messaging windows, derives internal delivery
slots, and keeps those exact slots out of the user-facing conversation. The study card is
compact and uses a midpoint content-swap flip animation; Space toggles front/back. Verification: 54 tests passed.
Railway hosting support is prepared with `railway.toml`, a native Python `Procfile`, a
platform-safe `/healthz` probe, and persistent `/data` volume instructions. No external
service has been deployed yet. Railway CLI login and Codex-agent integration succeeded;
project creation is currently blocked because the account's free trial has expired and
Railway requires a plan selection. A deploy attempt stopped before project creation; the
existing `HardlyHard` project was not modified. Resume after selecting the approximately
$5/month Railway Hobby plan and setting its usage controls.
No money was spent, no real texts or paid API calls were sent, no service was deployed, and
no package was published. See [SMS setup](sms-setup.md) and [deployment](deployment.md).
Physical-terminal animation feel is also available for owner inspection with `recall`.
