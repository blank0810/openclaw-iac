# Agent Backup + Restore — Design (V1)

**Date:** 2026-05-22
**Status:** Validated, implementing
**Scope:** Local zip backups of agent state on Server 3 (cron/systemd-timer) +
an async, job-tracked restore endpoint. Single host, current slug model. No
object store, no multi-host, no JWT (deferred). Builds on the existing
orchestrator (create/delete/provider-switch).

## What gets backed up

An agent's data is its bind-mounted **state dir** `/opt/zeroclaw/states/<slug>`
(`.zeroclaw/config.toml` + `workspace/` incl. `brain.db`, `sessions/`,
`memory/`). The agent *definition* (`agents/<slug>/agent.toml`) lives on the
orchestrator and persists across delete — restore relies on it still existing to
rebuild the container env (the LLM `api_key` flows via `ZEROCLAW_API_KEY`, which
is NOT in the state dir).

## Backup (host script, systemd timer)

`infra/files/zeroclaw-backup.py` — stdlib only (zipfile/os/datetime), runs as
root on Server 3 on a schedule (systemd timer + `Persistent=true`; the repo's
cron-equivalent, used already for the Slack watchdog). Each run:

- for every `/opt/zeroclaw/states/<slug>`: zip its contents →
  `/opt/zeroclaw/backups/<slug>/<YYYY-MM-DD>/<slug>.zip`
- log location + ok/fail to `/var/log/zeroclaw-backup.log`

`/opt/zeroclaw/backups` is **root-owned, mode 700** — zips contain
`config.toml` with Slack/Composio secrets. Deployed via pyinfra (script +
service/timer templates + dir + timer enable).

## Restore (`POST /v1/agent/restore/{date}`, async)

Body `{"name": "<slug>"}`. `date` is path param, validated `^\d{4}-\d{2}-\d{2}$`;
name validated against `SLUG_PATTERN`. Returns `202 {job_id}`; poll
`/v1/agent/job/{job_id}` (reuses JobStore + step streaming).

**Submit-time guards (before any mutation):**
- backup zip `/opt/zeroclaw/backups/<name>/<date>/<name>.zip` must exist → else `404`
- `agents/<name>/agent.toml` must exist (need it to rebuild the container) → else `404`

Path is **server-built from name+date** (no raw-path input) → no traversal, can
only restore that agent's own backup (spec's "same identity" rule).

**Background job steps** (`reprovision`-style, in `provisioner.restore_agent`):
1. `snapshot_current` — zip the current state dir →
   `/opt/zeroclaw/backups/<name>/_pre-restore-<ts>/<name>.zip` (recoverable if the
   restore is wrong)
2. `stop_remove` — stop + `remove(v=True)` the existing container (if any)
3. `extract` — **atomic**: unzip to a temp dir, then swap it into the state dir
   (a partial extract never corrupts live state)
4. `chown` — recursively chown the restored state to `65534:65534`
5. `ensure_network` + `run_container` — recreate from the existing
   AgentDefinition (build env + spec, run). Restored `config.toml` is kept (no
   re-render); current `agent.toml` supplies the env/api_key.

Restore **replaces** current state with the snapshot (current data is captured
in step 1 first). Job ends `succeeded` with the new container info.

## CLI + Postman

- `zc restore --name <slug> --date <YYYY-MM-DD>` → submit + poll + print result
- Postman: "Restore agent" (`PUT`/`POST /v1/agent/restore/{date}`, captures job_id)

## Out of scope (V1)

Object store upload, multi-host, JWT/firebaseid re-model, retention rules,
manual backup-trigger endpoint (backup stays cron-only per spec).
