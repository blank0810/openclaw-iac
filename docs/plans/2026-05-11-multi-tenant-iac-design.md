# Multi-tenant IaC — design

**Date:** 2026-05-11
**Status:** Approved for implementation.
**Replaces:** Current single-container ZeroClaw deploy in `infra/tasks/zeroclaw_deploy.py`.

## Goal

Replace the single hard-coded `zeroclaw` container with a multi-tenant model
where each tenant is its own isolated ZeroClaw deployment. Driven by a CLI
wrapper around Pyinfra so onboarding a new tenant is a single command.

Primary purpose: **tenant / customer isolation**. Each tenant has its own
Slack app, secrets, model provider, data, and container.

## Disk layout

### Laptop (repo)

```
ai-project/
├── .env                          # Host-level only: SERVER3_IP, SSH_KEY_PATH,
│                                 #   SSH_PORT, TZ. No tenant secrets.
├── tenants/
│   ├── .gitignore                # */.env (allow tenant.toml)
│   ├── agent-chaos/
│   │   ├── tenant.toml           # name, model, provider, agent_name,
│   │   │                         #   slack_mention_only, etc. Committed.
│   │   └── .env                  # SLACK_BOT_TOKEN, SLACK_APP_TOKEN,
│   │                             #   COMPOSIO_API_KEY, ANTHROPIC_API_KEY
│   │                             #   or LITELLM_API_KEY. Gitignored.
│   └── agent-edgar/
│       ├── tenant.toml
│       └── .env
├── docker/
│   └── agent/                    # Replaces docker/zeroclaw/. Templated.
│       ├── docker-compose.yml.j2
│       ├── config/config.toml.j2 # Moved from docker/zeroclaw/config/.
│       └── workspace/            # Same seed files as before.
└── infra/
    ├── deploy.py                 # Host-bootstrap: base + docker + probes
    │                             #   (no tenant deploy).
    └── tasks/
        ├── agent_new.py          # NEW. Per-tenant deploy/update.
        ├── agent_remove.py       # NEW. Per-tenant teardown + archive.
        └── agent_deploy_all.py   # NEW. Enumerate tenants/, include
                                  #   agent_new for each.
```

### Server 3

```
/opt/
├── agent-chaos/
│   ├── docker-compose.yml        # Rendered. container_name: agent-chaos.
│   ├── config/config.toml        # Rendered.
│   ├── data/                     # sqlite + workspace (UID 65534).
│   └── .env                      # Minimal: ZEROCLAW_IMAGE, TZ, AGENT_NAME.
├── agent-edgar/
│   └── ...
└── .archive/                     # Tombstones from `remove` w/o --purge.
    └── agent-edgar-20260511-0314/data/
```

## CLI surface (MVP — frozen)

```
agentctl init <name>     # Scaffold tenants/<name>/{tenant.toml, .env}
                         # from templates. No deploy.
agentctl new <name>      # Deploy. Requires init + populated .env first.
                         # Idempotent — re-running is the update path.
agentctl remove <name>   # Stop container, archive /opt/<name>/data/.
                         # Prompts "type the agent name to confirm".
agentctl list            # Table: name, container status, model, provider.
```

**Flags:**

| Command | Flags |
|---|---|
| `new` | `--dry-run` (pyinfra `--dry` passthrough) |
| `remove` | none |
| `list` | `--json` |
| `init` | `--provider {anthropic\|litellm}` (defaults to root .env) |

**Deferred:** `update` (covered by re-running `new`), `restart`, `logs`,
`status` (operator uses `ssh ... docker ...` directly), `--purge` (manual
`rm -rf /opt/.archive/*` until pain proves otherwise).

## Slug rules

`^agent-[a-z0-9][a-z0-9-]{1,28}$`. Mandatory `agent-` prefix is the
namespace marker that lets `remove` refuse to touch anything outside it.
Validated at the CLI wrapper, not in Pyinfra.

## Pyinfra task contract

Each `agent_*.py` reads `AGENT_NAME` from env (set by the wrapper),
validates the slug, and parameterises every path. The wrapper sources
root `.env` + `tenants/<name>/.env` before invoking pyinfra.

```python
agent_name = os.environ["AGENT_NAME"]
if not re.match(r'^agent-[a-z0-9][a-z0-9-]{1,28}$', agent_name):
    raise RuntimeError(f"invalid AGENT_NAME: {agent_name!r}")
agent_dir = f"/opt/{agent_name}"
```

`infra/deploy.py` (host bootstrap) includes `base_packages`, `docker_install`,
and the slack-probe units. It does NOT deploy any tenant. The watchdog
becomes per-tenant: `agent-<name>-slack-probe.{service,timer}`, deployed
by `agent_new`, removed by `agent_remove`.

## Compose template — key changes

- `container_name: {{ agent_name }}` (was hardcoded `zeroclaw`).
- All volumes bind to `/opt/{{ agent_name }}/...` (was `/opt/zeroclaw/...`).
- **Drop the host port mapping** `127.0.0.1:42617:42617`. Multiple
  tenants would conflict; gateway is only used internally + via
  `docker exec` for healthchecks. One less moving part.
- Hardening posture (`read_only`, `cap_drop: [ALL]`, `tmpfs /tmp`,
  `no-new-privileges`, `pids: 256`, `nofile` ulimits) preserved exactly.

## Remove semantics

`agentctl remove agent-edgar`:

1. Prompt: "type 'agent-edgar' to confirm".
2. `docker compose -f /opt/agent-edgar/docker-compose.yml down`.
3. `mv /opt/agent-edgar/data /opt/.archive/agent-edgar-YYYYMMDD-HHMM/data`.
4. `rm -rf /opt/agent-edgar/{docker-compose.yml,config,.env}`.
5. `systemctl disable --now agent-edgar-slack-probe.timer`.
6. Remove `/etc/systemd/system/agent-edgar-slack-probe.{service,timer}`.

Tenant data is recoverable from `/opt/.archive/` until an operator
manually cleans it up.

## Migration: existing `zeroclaw` → `agent-chaos`

One-time migration step (separate from MVP CLI; runnable as a Pyinfra
task or a shell script):

1. Create `tenants/agent-chaos/{tenant.toml, .env}` locally from current
   root `.env` values.
2. On host: `docker compose -f /opt/zeroclaw/docker-compose.yml down`.
3. On host: `mv /opt/zeroclaw /opt/agent-chaos`.
4. Rename container references in the rendered compose + config (or just
   re-render from the new templates).
5. `agentctl new agent-chaos` — brings it back up with new naming.
6. Remove old watchdog units (`zeroclaw-slack-probe.{service,timer}`).
7. Verify Slack round-trip works.

## Out of scope (explicit)

- Per-tenant TLS / public ingress.
- Cross-tenant data sharing.
- Auto-provisioning of Slack apps via API (manual workspace setup
  remains the operator's responsibility).
- Resource quota enforcement beyond the existing per-container limits.
- Tenant-level RBAC for the IaC itself.

## Open questions (deferred — not blocking MVP)

- When tenant count exceeds ~5, swap N per-tenant probe-timers for one
  global probe that enumerates `agent-*` containers.
- Optional: a `tenants/_template/` directory the `init` command copies
  from, so the operator can customise scaffolding without editing the
  CLI wrapper.
