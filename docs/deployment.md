# Deployment and restore runbook

The service is local by default. Nothing has been deployed and no real SMS was sent.

## Free personal hosting

For a personal always-on instance, use a free-tier Linux VM with persistent disk (for
example, an Oracle Cloud Always Free VM) and run the supplied Docker Compose stack. The
application and database stay on that VM; the Caddy sidecar terminates HTTPS. Free web
dyno tiers with an ephemeral filesystem are unsuitable because they can lose the SQLite
database on restart.

On the VM:

```sh
git clone YOUR_REPOSITORY recall
cd recall/deploy
cp ../.env.example .env
# Set RECALL_DOMAIN and a long random RECALL_TOKEN in .env.
docker compose up -d --build
docker compose exec recall recall doctor
```

Point `RECALL_URL` at the HTTPS domain when using the TUI or CLI from another machine.
Keep `RECALL_LIVE_SMS=false` until a sender, consent, webhook and spending limit are
deliberately configured. For personal AI calls, set `RECALL_LIVE_AI=true`,
`RECALL_ALLOW_UNEVALUATED_AI=true`, `RECALL_MODEL`, `OPENAI_API_KEY`, and a positive
`RECALL_MONTHLY_AI_TOKENS` in the deployment environment.

## Railway managed deployment

Railway can build this repository with its native Python builder; you do not need to run
Docker locally. Create a project from the GitHub repository, add a volume mounted at
`/data`, and set the service variables from `.env.example` with `RECALL_DB=/data/recall.db`.
The checked-in `railway.toml` starts the service on Railway's `$PORT` and uses `/healthz`
for the platform health check.

In Railway:

1. Create a project from the repository and deploy the service.
2. Add a persistent volume mounted at `/data` before putting real cards on the service.
3. Generate a public domain and set `RECALL_TOKEN` to a long random value.
4. Keep `RECALL_LIVE_SMS=false` initially. Add `OPENAI_API_KEY`, `RECALL_MODEL`,
   `RECALL_LIVE_AI=true`, `RECALL_ALLOW_UNEVALUATED_AI=true`, and
   `RECALL_MONTHLY_AI_TOKENS` only when you intentionally enable personal API calls.
5. From another machine, use `RECALL_URL=https://YOUR-RAILWAY-DOMAIN recall` and the same
   token. Verify `recall doctor` before importing or restoring your collection.

Railway's free trial includes temporary credits rather than guaranteed permanent free
hosting; monitor the project usage and configure its spending controls. The service's
single-worker SQLite design requires one replica and one attached volume.
One process owns one SQLite file; the service holds an OS file lock. Run one replica,
with WAL and the database on the same local persistent disk. Never share the live file
over a network filesystem. Stop the original service before moving the collection.

## Local installation

```sh
conda env create -f environment.yml
conda activate recall
recall init
recall serve
# Another terminal, same environment:
recall doctor
recall
```

No credentials are needed for manual study or simulation. `RECALL_DB` chooses an
explicit data file; `RECALL_URL` selects the service. `RECALL_TOKEN` sets owner API
authentication. A non-loopback bind requires at least 32 characters in that token.
Environment files are examples, not auto-loaded: export variables in your shell or
use Compose's env_file. Keep secrets outside the repository and protect their files.

## Prepare a host (requires authorization before deployment)

1. Choose a Linux host, persistent storage and a domain. Confirm the spending ceiling
   and obtain deployment approval. Configure DNS to the host and allow HTTPS/HTTP.
2. Copy `.env.example` to `deploy/.env` on the host, protect it with `chmod 600`, and
   set a strong `RECALL_TOKEN`. Keep `RECALL_LIVE_SMS=false` and `RECALL_LIVE_AI=false`
   initially. Set `RECALL_DOMAIN` to the DNS hostname (no scheme). The Compose environment
   used for interpolation must receive it via `--env-file deploy/.env`.
3. Review `docker compose --env-file deploy/.env -f deploy/compose.yaml config` locally.
   After deployment authorization, run
   `docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --build`.
4. Caddy terminates HTTPS; the app is reachable only inside the Compose network.
   Set `RECALL_PUBLIC_URL=https://your-domain` for canonical webhook validation.
   No trust in arbitrary forwarded hosts is needed for signatures.
5. Connect the TUI with `RECALL_URL=https://your-domain` and the same `RECALL_TOKEN`.
   Verify `recall doctor`, restore the data, and verify history before SMS enablement.
6. Follow sms-setup.md only after sender setup, consent and live authorization.

Container definition and Compose configuration are provided. See STATUS.md for the
actual local build/check evidence; a manifest is not a claim of hosted verification.
Image tags are explicit versions; revalidate image availability/security before deployment.

## Backups and restore drill

- `recall backup /explicit/path/snapshot.db` downloads a consistent SQLite snapshot
  using SQLite's backup API. The CLI refuses to overwrite an existing file.
- Before a schema upgrade, startup stores a local pre-migration snapshot under
  `DB_PARENT/backups/`. Restore also creates a pre-restore snapshot. Keep the latest
  seven local snapshots. Copy selected snapshots off-host yourself; Recall never
  uploads them silently. Protect backups: they contain your learning data and answers.
- For restore, run a separate service with an **empty** destination:

```sh
RECALL_DB=/absolute/path/restore/recall.db recall serve --port 8766
RECALL_URL=http://127.0.0.1:8766 recall restore /explicit/path/snapshot.db
RECALL_URL=http://127.0.0.1:8766 recall doctor
```

A restore preserves learning state, revisions, review/attempt history, edit proposals,
and delivery audit rows. It cancels unfinished inbox and queued sends, marks in-flight
sends uncertain, cancels active sessions, and starts opted-out and paused. It never
replays old messages. A full restore refuses a nonempty collection. JSON learning
imports likewise require an empty collection, and intentionally exclude transport queues
and pending assistant edit proposals. CSV/line imports add cards to an existing collection.

`python scripts/demo_manual.py` exercises actual process restart and exact scheduler
persistence. `pytest tests/test_operations.py tests/test_sms.py` exercises restore,
lease recovery, opt-out and uncertain sends with a controllable clock and fake transport.

## Operations

`GET /v1/diagnostics` reports schema, last worker tick, queue states, grading backlog,
last provider error, next eligible delivery slot, last downloaded backup, estimated and
provider-reported segments, and AI token reservations/usage. `recall doctor` reports
service readiness. Inspect uncertain sends in the provider console by callback attempt ID
and provider SID; do not blindly retry them. Signed status callbacks reconcile known attempts.
If unresolved, leave them uncertain and use the TUI until manually reconciled.

Shutdown supervision uses a 60-second grace period. Uvicorn uses one worker; Compose
restarts failed services. Explicitly test startup, disk-full behavior, HTTPS, and restore
on the chosen host before enabling phone delivery. Keep host/provider spending alerts too:
application segment/token allowances do not include all hosting, rental or carrier fees.
