# Recall — Spaced Repetition Agent

An animated terminal flashcard app and two-way SMS simulator sharing durable FSRS
review history. Python 3.12, Textual, FastAPI, SQLite and a single service process.
Manual study and simulation work without paid credentials. Real AI and phone access
are explicitly opt-in; the live phone pilot has not been performed.

```sh
conda env create -f environment.yml
conda activate recall
recall init
recall serve
# In another terminal:
recall
```

The service binds to `127.0.0.1:8765`. Data defaults to
`~/.local/share/recall/recall.db`. Override with `RECALL_DB`; connect to another server
with `RECALL_URL` and `RECALL_TOKEN`. Environment variables are not auto-loaded from `.env`.

The assistant can use the OpenAI API when explicitly enabled. For a personal deployment,
set `OPENAI_API_KEY`, `RECALL_LIVE_AI=true`, `RECALL_MODEL` and a positive
`RECALL_MONTHLY_AI_TOKENS`; set `RECALL_ALLOW_UNEVALUATED_AI=true` to skip the shared-
deployment evaluation gate. Assistant additions and edits are applied immediately. A text
such as `add eigenvector to my spaced repetition` sent to the configured SMS number is
handled as an assistant request even when no review session is active.

```sh
recall add kernel 'Inputs mapped to zero'
recall review
recall assistant 'add eigenvector'
recall sms setup
recall sms simulate MORE
recall export collection.md --format markdown
recall backup snapshot.db
recall doctor
```

The assistant's generated definitions and explicit edits are applied immediately for the
personal-use mode. The fixture grader is a deterministic simulator: unknown answers stay
pending for manual rating. Real semantic grading requires API access; shared deployments
should also use a reviewed live evaluation gate. Correct answers after hints preserve the
original first rating. The TUI opens on one study screen with the assistant beneath the
flashcard; collection and profile changes can be requested conversationally. The assistant
receives bounded card/profile data only, never API keys, passwords, source code, or shell
access.

Run local verification with `pytest`, `python scripts/demo_manual.py`,
`python scripts/demo_sms.py`, and `python evals/run_grader_eval.py`. Default tests use
fake providers and never contact a real phone or paid API. Dependencies are pinned in
`requirements.lock` / `requirements-dev.lock`; retain THIRD_PARTY_NOTICES.md when distributing.

- [Progress and acceptance evidence](docs/STATUS.md)
- [Product plan](docs/PROJECT_PLAN.md)
- [Build instructions](docs/CODEX_BUILD_INSTRUCTIONS.md)
- [Simulator and live account steps](docs/sms-setup.md)
- [Installation, deployment and restore runbook](docs/deployment.md)
- [Simulated transcript](docs/simulator-transcript.md)
- [Grading evaluation](evals/README.md)
