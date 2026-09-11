# Local acceptance evidence

The scenarios below map the project plan's essential gates to executable checks.
All providers in default tests are fixtures or mocks. No real SMS, paid AI call,
hosted deployment, sender registration or week-long phone pilot was performed.

| Plan scenario | Evidence |
|---|---|
| Reopen preserves cards, settings, scheduler and pending work | `test_restart_retry_and_backup`, `test_restart_recovers_pending_and_cross_channel_wins`, `test_restart_resumes_unfinished_terminal_episode`, `test_resume_probe_after_terminal_restart`; actual process/container restart demos |
| Duplicate requests/callbacks create one review | `test_concurrent_duplicate_reservations_and_ratings`, `test_full_session_verdicts_before_probe_duplicates`, signed webhook dedup test |
| Initial answer updates once; hints do not replace it | `test_probe_preserves_first_attempt`, `test_multiple_probes_partial_and_bare_reply`, simulator transcript |
| Missing/ungradable/error/expired answers do not become Again | `test_unknown_fixture_stays_pending`, bounded failure tests, stale/expiry SMS tests, expired second grading lease test |
| TUI completion prevents late SMS regrading | `test_bad_codes_unknown_items_expiry_and_cross_channel`, `test_unsent_prompt_cancelled_after_tui_completion` |
| A later due card gets a new episode in the same TUI session | `test_correction_and_legitimate_second_episode` |
| Wrong code, unknown number or stale revision cannot change schedule | SMS bad-code/item tests, `test_stale_revision_and_state`, `test_edit_during_provider_call_discards_result` |
| Quiet hours, midnight/DST and missed slots avoid duplicate/burst dispatch | `test_budget_quiet_and_dst`, daily/new allowance tests, stale queued prompt test; persisted unique slot keys |
| STOP cancels queued work without invoking grading | `test_stop_cancels_before_grading_and_resume_not_start`, `test_stop_during_grade_discards_result`, old START replay tests |
| Uncertain acceptance is not blindly retried | `test_restart_inbox_and_uncertain_not_retried`; callback reconciliation and callback-before-send-return tests |
| Backup/export/import preserve documented data without queue replay | learning round-trip tests, `test_restore_keeps_history_and_cancels_queues`, `test_json_export_is_one_consistent_snapshot` |
| Animation is safe under resize/rapid input and does not leak answers | parameterized `test_keyboard_study` at 80×24/120×36 and motion on/off, typed digits/spaces test, captured front/back renders |

Additional checks cover draft approval, selected-ID and owner-intent restrictions,
latest-review correction, service file locking, pre-migration backups, segment encoding,
toll-free segment differences, concise SMS labels, malformed multi-item grading output,
Responses SDK request shape, and live configuration remaining disabled by default.

## Commands

```sh
conda activate recall
pytest -q
ruff check src tests scripts evals
ruff format --check src tests scripts evals
python -m pip check
python evals/run_grader_eval.py
python scripts/demo_manual.py
python scripts/demo_sms.py
python scripts/capture_tui.py
```

Clean installation was also checked in a separate non-editable Python 3.12 venv
using `requirements-dev.lock`, with `pip check`, fresh initialization and the actual
CLI/process restart demo. The local Python HTTPS workaround is in decisions.md;
container builds downloaded the pinned dependencies normally.

```sh
docker build -f deploy/Dockerfile -t recall-local:verification .
python scripts/demo_container.py
```

The container drill uses `--network none`, no published ports, a fake owner token,
and no live credentials. It verifies authenticated health, add/rate and exact review
persistence after `docker restart`, then removes its own container. This is local
execution, not a hosted deployment. Compose configuration was rendered with a temporary
nonsecret env file; Caddy's `validate` command passed in an isolated local container.

## Limits of the evidence

The 63-case offline grader run proves fixture/schema consistency only. Its 100% replay
agreement and zero designated false-Right results do not measure a live model. The data
and probe labels need independent human review, followed by explicitly authorized live
model evaluation. Production live grading rejects an unreviewed or mismatched report.

Rendered compact/large screens were inspected; automated tests verify a reserved layout
through flips. Physical terminal animation smoothness remains an owner usability check.
Live carrier delivery, registration, current total costs, hosted HTTPS/restarts and a
week of personal usage remain M7. See sms-setup.md and deployment.md for exact setup.
