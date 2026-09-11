# Codex implementation handoff

Use this with `PROJECT_PLAN.md`. The plan records the product decisions; these instructions keep implementation scoped and verifiable. The application has not been built yet.

## Starter prompt

Paste the following into Codex from the intended project directory and attach the plan, or replace the placeholder with its full local path:

```text
Build the application specified in docs/PROJECT_PLAN.md.

Read the plan and inspect this workspace before changing files. Treat the plan as the implementation specification. Use its architecture and defaults unless current dependency documentation or existing repository constraints show a concrete reason to change them. Record deviations briefly.

The required product is an animated terminal flashcard app with a shared FSRS review history and concise SMS reviews graded by an LLM. Preserve these behaviors:
- Grade every submitted answer Right/Wrong before any probing question.
- Accept semantically correct paraphrases. A close but incomplete answer is Wrong plus one targeted probe.
- Preserve the first-attempt rating after hints; a probe is teaching, not a new successful recall event.
- Missing/ungradable answers and system failures stay pending.
- The same episode must never update scheduling twice, including across TUI/SMS.
- The LLM cannot directly schedule, modify storage, or send messages.
- Manual local study and the complete SMS simulator work without paid credentials.

Use docs/PROJECT_PLAN.md as the specification and maintain a concise docs/STATUS.md with milestones, commands, verification evidence, and remaining work. Add only practical repository guidance to AGENTS.md.

Work in order through M0–M6. Each milestone must have a working demonstration and its relevant acceptance checks before moving on. Do not stop at scaffolding or a plan, and do not rewrite working foundations when continuing a later milestone. Use fake providers and a controllable clock in default tests. Keep source dependencies locked and secrets outside version control.

Make reasonable reversible decisions. Continue all work that does not depend on missing credentials. Obtain authorization before purchasing services, deploying, publishing packages, or sending real texts. Report live integration limits honestly. M7 begins only when the needed account setup and authorized live access are available.

Start with the first incomplete milestone and continue through the available implementation work. Keep updates brief: what now works, what was verified, and what comes next.
```

## Milestone-sized follow-up prompts

Use these when continuing in a fresh Codex session or narrowing a difficult implementation step. Each assumes the previous milestones' gates have passed; otherwise finish the missing prerequisites first.

### M0 — Make the project runnable

```text
Read docs/PROJECT_PLAN.md and docs/STATUS.md. Complete M0: installable Python package, separate Conda environment definition, pinned dependencies, minimal CLI/API health check, migrations, license notes, and credential-free test setup. Verify installation in the intended environment. Record exact working commands and dependency versions. Avoid building future screens or integrations in this step.
```

### M1 — Make learning data durable

```text
Complete M1 from the project plan. Implement approved/draft cards, immutable content revisions, search/import/export, the FSRS adapter, review episodes, explicit ratings, idempotent updates, and latest-review correction. Test persistence after restart, repeated requests, stale state versions, and a backup/restore round trip. Keep new review episodes distinct from retries and hints. Demonstrate a complete manual CLI review before moving on.
```

### M2 — Make terminal study feel good

```text
Complete M2 using the existing application API. Build Today, Collection, Study, History, and Settings. Implement flip-and-self-rate and the typed-answer interface, a brief flip animation, keyboard controls, compact layouts, and reduced motion. Verify at 80x24 and 120x36, including long definitions, Unicode, rapid keypresses, and resizing mid-animation. Animation and navigation must never create review events themselves.
```

### M3 — Grade and teach reliably

```text
Complete M3. Implement the configurable LLM adapter, strict grading result schema, exact episode-ID validation, first-attempt persistence, and one-probe teaching flow. No direct model tools in the grader. Preserve initial Wrong/Again after a successful probe. API failures, refusals, invalid output, and ambiguous references stay pending. Add the specified labeled grading cases and an opt-in live evaluation command; default tests use fixtures. Do not claim the live quality gate passed without running it.
```

### M4 — Prove the complete phone workflow locally

```text
Complete M4 with the local SMS simulator. Implement session codes, numbered answer parsing, verdict-first replies, partial answers, queued probes, message segmentation, delivery slots/quiet hours, durable inbox/outbox, and restart recovery. Use the same review application service as the TUI. Verify duplicates, stale codes, cross-channel completion, opt-out, budget limits, DST, missed slots, and uncertain outbound acceptance. Show an end-to-end simulated transcript with the resulting review history.
```

### M5 — Add useful conversational management

```text
Complete M5. Add bounded collection-assistant operations for searching, drafting definitions, approved additions/edits, archiving/restoring explicit cards, explanations/comparisons, and exports. Reuse the provider layer but keep assistant tools separate from the grader. Validate tool arguments and selections in application code. Generated definitions require approval; removal is recoverable. Verify that card text and learner answers cannot cause management actions.
```

### M6 — Prepare real SMS and deployment

```text
Complete M6. Implement the Twilio adapter and signed inbound/status callbacks, owner phone restrictions, STOP/START integration, service diagnostics, safe backup/restore, and single-replica deployment files. Test provider behavior with mocks and local contract tests. Document exact account/sender/country setup and cost assumptions. Do not buy a number, deploy, or send messages without authorization. Finish all code and local checks even if real credentials are unavailable; list only the remaining live requirements.
```

### M7 — Run the authorized pilot

```text
Read the current plan and status. Carry out only the live steps already authorized in this conversation. Verify one real phone conversation, a partial answer, a probing exchange, a duplicate callback, pause/opt-out, and scheduling with the selected service running. Confirm no cross-channel duplicate review and no resend after restart/restore. Keep within the approved recipient and spending limits. Record observed outcomes separately from simulated results and fix pilot defects.
```

## Status format for the implementing agent

```text
Milestone:
Implemented:
Verification run and result:
Commands to demonstrate it:
Known limitation:
Next incomplete work:
```

Do not replace implementation evidence with long planning summaries. A milestone is complete only when its gate is demonstrated. A missing external account is a reason to defer that live check, not to leave unrelated local features unfinished.
