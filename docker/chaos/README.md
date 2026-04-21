> **⚠️ SUPERSEDED 2026-04-21** — OpenClaw/Chaos is permanently out of
> project scope. The files in this directory remain as historical record
> (commit `1e19c5c`) but the stack is no longer deployed, and the
> `chaos_deploy.py` task is no longer included in `infra/deploy.py`.
> Do not reintroduce without a decision to reverse course.

# Chaos — OpenClaw 4.14, Gateway-Only (HISTORICAL)

Single-container OpenClaw stack. Was deployed to `/opt/openclaw/chaos/`
on Server 3 by `infra/tasks/chaos_deploy.py` between 2026-04-19 and
2026-04-21. Torn down 2026-04-21.

See `docs/plans/2026-04-18-chaos-gateway-only-design.md` for the full
spec (also superseded).

## Deploy

From the repo root on your laptop:

```bash
# 1. Fill local .env with SERVER3_IP, SSH_KEY_PATH, and all CHAOS_* vars.
# 2. Run the standard deploy (idempotent):
pyinfra infra/inventories/deploy.py infra/deploy.py
```

`chaos_deploy.py` runs at the end of the deploy flow. It uploads compose +
config + remote `.env`, runs `docker compose up -d`, polls `/healthz`, and
runs `openclaw config validate`. Any failure aborts the run.

## Access

```bash
ssh -L 18789:127.0.0.1:18789 -p 2222 overlord101@<SERVER3_IP>
# then open http://localhost:18789 in a browser
# paste CHAOS_GATEWAY_TOKEN when prompted
```

## Recovery (one-liners per failure mode)

Run these from the chaos directory on the server:

```bash
cd /opt/openclaw/chaos
```

| Symptom | First command to run |
|---|---|
| `docker compose up -d` non-zero exit (bad image digest / bad compose) | `docker compose config && docker compose pull` |
| Container crash-loops within 240s (validator rejected a key) | `docker compose logs --tail=200 chaos` |
| `/healthz` never becomes green (app up but gateway not binding) | `docker compose exec chaos wget -qO- http://127.0.0.1:18789/healthz; docker compose logs --tail=200 chaos` |
| Prompts hang or return 401 (wrong LITELLM base URL / token) | `docker compose exec chaos sh -c 'wget -qO- --header="Authorization: Bearer $CHAOS_LITELLM_API_KEY" $CHAOS_LITELLM_BASE_URL/models'` |

For any of the above, a rerun of `pyinfra infra/inventories/deploy.py
infra/deploy.py` is safe and the usual next step after fixing `.env` or
the image pin.

## What's intentionally absent

Slack, SearXNG, fs/web tools, public exposure, TLS, backups, and a second
agent are all out of scope for day one. Each has a scaffolding slot
(compose network, workspace volume, `CHAOS_*` env placeholders, empty
`channels` / `plugins` in config) so future diffs are config-only. See
the design doc's "Follow-ups" section.
