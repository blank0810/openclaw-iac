# ZeroClaw Infra Rewrite — Design

**Date:** 2026-05-14
**Status:** Validated, ready for implementation planning
**Scope:** Full ground-up rewrite of `infra/` + `scripts/agentctl.py` into a nanobot-shaped, single-CLI infrastructure tool for the ZeroClaw runtime.

> Note: terminology was later changed `tenant` -> `agent` to match nanobot conventions. Read with that substitution.

## Background

A council review (lead-engineer + zeroclaw-engineer) compared our current `infra/` against the
third-party `nanobot-infra` reference. Verdict: nanobot is a *product* (typed config model +
single CLI + bidirectional state sync + tests); ours is a *script collection with a multi-tenant
CLI bolted on*, with two ~95%-duplicate deploy paths (`zeroclaw_deploy.py` and `agent_new.py`).

Decision: rewrite our infra to nanobot's shape, adapted for the ZeroClaw runtime, while keeping
the things we already do better than nanobot (container hardening, per-tenant network isolation,
Ubuntu 24.04 `ssh.socket` correctness, the Slack-deafness watchdog). The
`AGENT_CHECKLIST.md` baseline is treated as a first-class constraint and gets a per-project
`SECURITY.md` deliverable.

### Key decisions locked during brainstorming

| Decision | Choice |
|---|---|
| Rewrite scope | Full ground-up rewrite to nanobot shape |
| Tenancy model | Shared `/opt/zeroclaw/docker-compose.yml` with N services, `states/<slug>/` per tenant |
| Secrets layer | Env-only — all secrets in `states/<slug>/zeroclaw.env` (chmod 0600), zero secrets in `config.toml` |
| Entry point | Single CLI (`zeroclawctl`) with auto-detecting bootstrap-vs-deploy |
| Workspace files | Keep our 7-file set (AGENTS, BOOTSTRAP, HEARTBEAT, IDENTITY, SOUL, TOOLS, USER), glob-driven sync |

### Verified constraint

ZeroClaw does **not** interpolate `${VAR}` placeholders inside `config.toml` strings
(checked `apps/zeroclaw/upstream/crates/zeroclaw-config/`). It *does* read many env vars
natively (`ZEROCLAW_API_KEY`, `ANTHROPIC_API_KEY`, `ZEROCLAW_PROVIDER`, `ZEROCLAW_MODEL`,
`ZEROCLAW_GATEWAY_PORT`, `ZEROCLAW_WORKSPACE`, etc.). The env-only secrets model is built
around this reality — nanobot's exact placeholder pattern does not port.

---

## Section 1 — Repo layout + entry point

Pyinfra moves from "the thing you run" to "a library the CLI drives" (same as nanobot's
`deploy.py` calling `connect_all` / `run_ops` directly).

```
ai-project/
├── zeroclawctl.py          # CLI entry point (was: pyinfra invocations + agentctl)
├── lib/
│   ├── __init__.py
│   ├── config.py           # DeploymentConfig + TenantDefinition dataclasses + load_config()
│   ├── inventory.py        # pyinfra inventory builder (wraps load_config)
│   ├── bootstrap_prepare.py    # pyinfra deploy file (root) — create deploy user, Docker/UFW
│   ├── bootstrap_hardening.py  # pyinfra deploy file (root) — sshd drop-in, fail2ban, ssh.socket
│   ├── deploy_runtime.py   # pyinfra deploy file (overlord101) — render compose, pull image
│   ├── tenants.py          # cmd_create / cmd_deploy / cmd_status / cmd_fetch / cmd_shell / cmd_remove
│   ├── workspace.py        # cmd_fetch / cmd_deploy / cmd_status / cmd_session_clear (glob-driven)
│   ├── tenant_env.py       # build_tenant_env() — assemble real secrets dict from tenant.toml
│   ├── config_patch.py     # exec-deny pattern injection into rendered config.toml
│   ├── managed_policy.py   # BEGIN/END policy block injection into AGENTS.md
│   ├── tenant_sync.py      # plan_tenant_changes(desired, actual) -> to_create/keep/remove
│   └── slack_probe.py      # systemd-timer probe wiring (our existing win, preserved)
├── templates/
│   ├── docker-compose.yml.j2    # one service per enabled tenant + our hardening flags
│   ├── zeroclaw.env.j2          # per-tenant env file (real secrets)
│   ├── config.toml.j2           # per-tenant config (zero secrets)
│   ├── workspace/*.md.j2        # 7 workspace seeds
│   ├── sshd_config.d/60-cloudesk.conf.j2    # drop-in (deltas only)
│   ├── jail.local.j2
│   └── systemd/zeroclaw-slack-probe.{service,timer}.j2
├── tenants/                # gitignored; per-tenant local source of truth
│   └── <slug>/
│       ├── tenant.toml
│       ├── cron.toml       # optional
│       └── workspace/      # local mirror of remote workspace files
├── tests/                  # pytest, mocks SSH/Docker, tmp_path fixtures
├── backups/                # gitignored; populated by `zeroclawctl backup`
├── docs/plans/             # design docs (incl. this one)
├── group_data/all.py       # KEPT — pyinfra-native non-secret host facts
├── .env.example            # server host + ssh keys + image tag
├── SECURITY.md             # NEW — per-project security implementation doc
├── AGENT_CHECKLIST.md      # immutable baseline
├── CLAUDE.md
├── AGENTS.md
└── README.md
```

**Killed:** `infra/bootstrap.py`, `infra/deploy.py`, `infra/inventories/`, `infra/tasks/*`,
`infra/files/sshd_config` (whole-file replacement → drop-in), `scripts/agentctl.py`,
`docker/zeroclaw/`, `docker/agent/`.

**Kept:** `group_data/all.py`, `apps/zeroclaw/upstream/`, `apps/slack-agent/`, container
hardening flags, `ssh.socket` restart sequence, Slack-deafness systemd-timer probe.

---

## Section 2 — CLI command surface

Three namespaces. Tenant-scoped commands take `--name <slug>`.

| Command | What it does |
|---|---|
| `zeroclawctl server deploy` | TCP-probe 22 → try deploy-user → fall back to root. Root-only: `bootstrap_prepare` → verify deploy key → `bootstrap_hardening` → `deploy_runtime`. Deploy-user works: just `deploy_runtime`. Idempotent. |
| `zeroclawctl tenants create --name X` | Scaffold `tenants/X/{tenant.toml, cron.toml, workspace/*.md}` from `tenants/_template/`. Local-only. Interactive getpass prompts for secrets. |
| `zeroclawctl tenants deploy --name X [--pull-image]` | Auto-detects new vs existing. New: `deploy_runtime` to register service, render env + config, inject policy block, `up -d X`. Existing: re-render, sync policy, `up -d --force-recreate X`. |
| `zeroclawctl tenants status` | List configured tenants; probe each: running? listening? config drift? last probe restart? |
| `zeroclawctl tenants fetch --name X` | Round-trip remote `config.toml` + `zeroclaw.env` + `workspace/*.md` back into `tenants/X/`. Prompts if local exists. |
| `zeroclawctl tenants shell [--name X]` | SSH + `docker compose exec X bash`. Interactive. |
| `zeroclawctl tenants remove --name X` | Type-name-to-confirm. Stop service, archive `states/X/` to `.archive/`, remove from compose, recreate. |
| `zeroclawctl tenants restore --name X [--from <ts>]` | Un-archive from `/opt/zeroclaw/.archive/` and redeploy. |
| `zeroclawctl tenants logs --name X [--follow]` | Wrapper over `ssh + docker compose logs`. |
| `zeroclawctl workspace status --name X` | Read-only per-file diff: `same / different / local_only / remote_only`. |
| `zeroclawctl workspace fetch --name X` | Pull remote workspace markdowns into local. Prompts. |
| `zeroclawctl workspace deploy --name X` | Push local workspace markdowns to remote. Prompts. |
| `zeroclawctl workspace session-clear --name X` | Archive remote `workspace/sessions/*.jsonl`, restart container. |
| `zeroclawctl backup [--name X \| --all]` | SSH-pull `states/<slug>/{config.toml,workspace/}` (NOT secrets) into `backups/<slug>/<ts>/`. |
| `zeroclawctl audit [--tenant X] [--since DATE]` | Read back `/opt/zeroclaw/audit.log`. |

**Footgun guards:** `server deploy` refuses hardening until deploy-key auth verified;
`tenants remove` requires typing the slug; `workspace deploy/fetch` print a diff and prompt;
`tenants deploy` refuses on missing/empty secrets unless `--allow-empty-secrets`.

---

## Section 3 — Bootstrap → deploy flow

Phase decision tree inside `zeroclawctl server deploy`:

```
TCP-probe host:22
 ├─ unreachable → ERROR exit 1
 └─ open
     ├─ try ssh overlord101@host (deploy key)
     │   └─ OK → run lib/deploy_runtime.py as overlord101 → DONE
     └─ FAIL → try ssh root@host
         ├─ FAIL → ERROR "can't auth as deploy user or root"
         └─ OK → BOOTSTRAP PATH:
             1. run lib/bootstrap_prepare.py as root@22
             2. RE-CHECK: ssh overlord101@host with deploy key
                 ├─ FAIL → ERROR, halt. Root SSH still works. Fix and retry.
                 └─ OK → continue
             3. run lib/bootstrap_hardening.py as root@22
             4. run lib/deploy_runtime.py as overlord101@2222
```

The re-check between steps 1 and 3 is the lockout-prevention gate — hardening is refused
until the deploy key is proven to work.

**`lib/bootstrap_prepare.py`** (root@22): create `overlord101` + pubkey + passwordless sudo;
`apt install git ufw fail2ban ca-certificates curl`; install Docker via official keyring
(idempotent `command -v` guard); add user to `docker` group; create `/opt/zeroclaw/{,states}`;
render `jail.local.j2`; UFW default-deny-incoming + allow-outgoing + allow `22` AND `2222` +
enable; enable fail2ban.

**`lib/bootstrap_hardening.py`** (root@22): render `sshd_config.d/60-cloudesk.conf.j2` drop-in
(`Port 2222`, `PermitRootLogin no`, `PasswordAuthentication no`, `PubkeyAuthentication yes`,
`AllowUsers overlord101`); `systemctl daemon-reload`; restart **`ssh.socket`** (not
`ssh.service` — Ubuntu 24.04 correctness); UFW remove `22/tcp`.

**`lib/deploy_runtime.py`** (overlord101@2222): ensure dirs + ownership; render
`docker-compose.yml.j2` (one service per enabled tenant); ensure per-tenant
`states/<slug>/{workspace,workspace/sessions}`; `docker pull` only when image tag changed;
install per-tenant systemd-timer Slack probes.

All ops idempotent. Re-running `server deploy` on a bootstrapped server is a re-render + restart-changed.

---

## Section 4 — Tenant model + state layout

**Local source of truth** (gitignored): `tenants/<slug>/{tenant.toml, cron.toml, workspace/*.md}`.

**`tenant.toml`** — single typed source of truth per tenant:

```toml
[identity]
name = "acme"              # = <slug>; validated unique, [a-z0-9-]
display_name = "Acme Corp Assistant"
enabled = true
state_dir = "acme"         # remote dir; defaults to name

[runtime]
image = "ghcr.io/.../zeroclaw:1.4.2"   # optional; falls back to .env default
host_port = 0              # 0 = no host port; else 127.0.0.1:N:42617

[llm]
provider = "anthropic"     # anthropic | litellm
model = "claude-sonnet-4-5"
api_key = "sk-ant-..."     # SECRET — never lands in remote config.toml
timeout_secs = 60

[slack]
enabled = true
bot_token = "xoxb-..."     # SECRET
app_token = "xapp-..."     # SECRET
signing_secret = "..."     # SECRET

[composio]
enabled = true
api_key = "comp-..."       # SECRET
allowed_tools = ["gmail.send", "gcal.create_event"]

[exec]
enabled = false            # true → managed exec_deny_patterns auto-injected

[policy]
require_approval_for = ["send_email", "delete_record", "modify_crm"]
denied_domains = ["*.gov", "*.mil"]
```

**Typed config layer** (`lib/config.py`): frozen `TenantDefinition` (with nested frozen
`LlmConfig` / `SlackConfig` / `ComposioConfig` / `PolicyConfig`) and `DeploymentConfig`.
`load_config()` reads `.env`, scans `tenants/*/tenant.toml` (skips `_template` and `_`-prefixed
dirs), validates unique slugs / state_dirs / non-zero host_ports, validates required secrets
present unless `--allow-empty-secrets`. This single function kills the duplicate env-parsing
between today's `zeroclaw_deploy.py` and `agent_new.py`. Every CLI subcommand and every pyinfra
deploy file consumes the validated object.

**Remote state layout** (`/opt/zeroclaw/`, owned overlord101):

```
/opt/zeroclaw/
├── docker-compose.yml         # rendered, N services
├── audit.log                  # operator action JSONL
├── states/<slug>/
│   ├── zeroclaw.env           # chmod 0600 — REAL secrets
│   ├── config.toml            # chmod 0644 — ZERO secrets
│   └── workspace/
│       ├── AGENTS.md           # contains MANAGED SECURITY POLICY block
│       ├── ... (6 others)
│       └── sessions/
│           ├── *.jsonl         # ZeroClaw writes
│           └── archive/        # populated by workspace session-clear
└── .archive/<slug>-<ts>/      # populated by tenants remove
```

**`docker-compose.yml.j2`** — nanobot's per-tenant service loop with our hardening flags:
`read_only: true`, `tmpfs /tmp:rw,noexec,nosuid,size=64m`, `cap_drop: [ALL]`,
`security_opt: [no-new-privileges:true]`, `user: "65534:65534"`, per-tenant `zc-<name>`
bridge network, `deploy.resources.limits` (cpus/memory/pids), `ulimits.nofile`,
`logging: json-file` with bounded retention. Host port only mapped when `host_port != 0`.

**Per-tenant bridge networks** recover the inter-tenant isolation we'd otherwise lose by
moving from per-directory compose projects to a shared compose file.

**Recovery** (`tenants fetch`): read remote `config.toml` + `zeroclaw.env`, SCP `workspace/*.md`,
reconstruct `tenants/<slug>/tenant.toml`. Prompts if local exists; `--force` to override.

---

## Section 5 — Credential, policy, and exec-deny layer

Three concentric defences.

### Layer A — Secret hygiene (env-only)

No secret value lands in a file that is not chmod 0600. `lib/tenant_env.py`
`build_tenant_env(tenant)` assembles a dict of real secrets keyed by the env vars ZeroClaw
reads natively (`ANTHROPIC_API_KEY` / `LITELLM_API_KEY`, `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`,
`SLACK_SIGNING_SECRET`, `COMPOSIO_API_KEY`, plus non-secret `ZEROCLAW_MODEL` /
`ZEROCLAW_PROVIDER` / `ZEROCLAW_WORKSPACE`). Rendered via `zeroclaw.env.j2` into
`states/<slug>/zeroclaw.env` mode 0600, loaded by compose `env_file:`. `config.toml` has
**zero** secret-bearing fields.

### Layer B — Managed security policy block

`lib/managed_policy.py` injects a `<!-- BEGIN/END MANAGED SECURITY POLICY -->` fenced block
into the remote `AGENTS.md` on every `tenants deploy`. Replace-in-place preserves content
outside the block. The block instructs the agent to refuse, with no preamble: credential
disclosure, reading `.env` / `config.toml` / `/etc` / `/root` / `/home`, env-enumeration
shell commands, and bypassing `policy.require_approval_for` gates. Operator-defined approval
gates and denied domains are templated into the block. This is the prompt-injection defence.

### Layer C — Exec deny patterns

When `[exec] enabled = true`, `lib/config_patch.py` writes a `[security.exec].deny_patterns`
table into the rendered remote `config.toml` (`env`, `printenv`, `cat *.env`,
`cat */zeroclaw.env`, `python -c*os.environ`, `curl*169.254.169.254`, etc.). Omitted entirely
when `exec` is disabled.

**Open question (flag, do not block):** if ZeroClaw upstream does not currently honor
`[security.exec].deny_patterns`, ship the table anyway as documentation and rely on Layer B
for now; revisit (patch upstream + PR) when the upstream exec tool is audited.

| Attack | A | B | C |
|---|---|---|---|
| Operator leaks key in committed config | ✓ | — | — |
| Agent socially-engineered to read its own `.env` | partial | ✓ | ✓ |
| Hostile inbound prompt-injection | — | ✓ | — |
| Agent enumerates env via `printenv` | — | ✓ | ✓ |
| Container compromise (RCE) | partial (read_only + cap_drop) | — | — |

---

## Section 6 — Logging, audit trail, backup & recovery

### Logging & audit (§8)

1. **Container stdout/stderr → journald** via compose `logging: json-file` with bounded
   retention (`max-size: 10m`, `max-file: 5`). `zeroclawctl tenants logs` wraps it.
2. **Deploy audit log** — every mutating `zeroclawctl` command appends one JSONL line to
   `/opt/zeroclaw/audit.log` (ts, actor, cmd, tenant, image, result). `zeroclawctl audit`
   reads it back. Operator-level audit; agent-level tool-call audit is ZeroClaw's own
   session JSONLs, preserved under `workspace/sessions/`.
3. **Slack-deafness probe logs** — existing systemd-timer watchdog; restart events to
   journald, surfaced by `tenants status`.

### Backup & recovery (§9)

| Failure | Recovery path |
|---|---|
| Lost local `tenants/<slug>/` | `tenants fetch --name X` reconstructs from live server |
| Bad deploy / corrupt config | `tenant.toml` is source of truth; re-run `tenants deploy` |
| Accidental removal | `tenants restore --name X [--from <ts>]` un-archives + redeploys |
| Total server loss | `server deploy` rebuilds host + runtime; `tenants deploy` per tenant; `zeroclawctl backup` restores accumulated workspace content |

**Workspace-content gap:** `tenant.toml` + templates rebuild *seed* state only. `zeroclawctl
backup [--name X | --all]` SSH-pulls `states/<slug>/{config.toml,workspace/}` (not
`zeroclaw.env`) into timestamped local `backups/<slug>/<ts>/`. This is the one genuinely new
capability beyond "port nanobot."

**Out of scope for v1:** remote object-storage sync (restic/rclone to Hetzner Storage Box).
Local `backup --all` covers the solo-dev case; add remote backup with a second operator/SLA.

### Monitoring posture

No Prometheus/Grafana — disproportionate for solo-dev single-host. Surface is `tenants status`,
`tenants logs`, `audit`, and the systemd-timer Slack probe (the only active monitor). Revisit
with a metrics stack only at 10+ paying-customer tenants.

---

## Section 7 — Testing posture & SECURITY.md

### Testing posture (~600 LOC target, all mocked SSH/Docker)

| Target | Why | Effort |
|---|---|---|
| `lib/config.py` `load_config()` + validation | Highest ROI — catches dup slugs, missing secrets, malformed toml pre-server | ~200 LOC |
| Template rendering | Catches renamed-field breakage; **asserts no secrets in `config.toml` output** | ~150 LOC |
| `lib/tenant_env.py` | Asserts secrets route to env, nothing leaks to config | ~80 LOC |
| `lib/managed_policy.py` | Asserts BEGIN/END replace-in-place preserves surrounding content | ~80 LOC |
| `lib/tenant_sync.py` | Pure function — guards create/keep/remove diff | ~60 LOC |
| CLI arg parsing | Cheap smoke test for argparse wiring | ~50 LOC |

**Not tested:** pyinfra deploy files (straight-line idempotent ops; rely on `--dry`).
**Dedicated security test:** `test_no_secrets_in_config.py` renders every template with a
secret-laden fixture and greps the output for known secret values — fails if any appear
outside `zeroclaw.env`.

### SECURITY.md deliverable

AGENT_CHECKLIST mandates a per-project `SECURITY.md`. Written as part of this rewrite,
structured 1:1 against the checklist's 10 sections, each stating *the actual implementation*.
N/A items get an explicit "not required because…" line.

| § | Implementation |
|---|---|
| §1 Agent Identity | `workspace/` templates; managed policy block |
| §2 Customer Isolation | per-tenant `states/<slug>/`, bridge network, env file |
| §3 Server Hardening | `bootstrap_hardening.py`: sshd drop-in, UFW deny-incoming, fail2ban, port 2222 |
| §4 Tool Permissions | `composio.allowed_tools` allowlist, `policy.denied_domains`, `exec.enabled` gate |
| §5 Secrets | env-only, `zeroclaw.env` 0600, zero secrets in config.toml; `test_no_secrets_in_config.py` |
| §6 Memory/Privacy | per-tenant `workspace/`, `session-clear` archival, no cross-tenant mounts |
| §7 Approval/Safety | `policy.require_approval_for` gates rendered into config + policy block |
| §8 Logging/Audit | json-file bounded retention, `/opt/zeroclaw/audit.log`, Slack probe |
| §9 Backup/Recovery | `tenants fetch`, `tenants restore`, `zeroclawctl backup`, `server deploy` rebuild |
| §10 Testing/Cost | pytest suite (~600 LOC), `--dry` runs; cost = LiteLLM routing (Server 2) |

---

## Migration plan

Single feature branch off `main`, six independently-reviewable steps:

1. **Scaffold `lib/config.py` + `tests/`** — typed dataclasses + `load_config()` + validation
   tests. No behavior change, nothing wired.
2. **Port pyinfra deploy files** — `infra/tasks/*` + `infra/bootstrap.py` + `infra/deploy.py`
   → `lib/bootstrap_prepare.py`, `lib/bootstrap_hardening.py`, `lib/deploy_runtime.py`.
   Whole-file `sshd_config` → drop-in template. Keep `ssh.socket` restart.
3. **Build `zeroclawctl.py` + `lib/tenants.py` + `lib/workspace.py`** — CLI surface from
   Section 2. `agentctl` stays alive in parallel until step 6.
4. **Port templates** — `docker/*` → `templates/*`, merge hardening flags into the
   nanobot-shape compose loop, add per-tenant networks.
5. **Add new capabilities** — `tenant_env.py`, `managed_policy.py`, `config_patch.py`
   exec-deny, `audit` log, `backup` command.
6. **Cutover** — migrate live tenant(s) via `tenants fetch` against the running server,
   verify `tenants status` matches reality, delete `infra/`, `scripts/agentctl.py`,
   `docker/`. Write `SECURITY.md`. Update `CLAUDE.md`.

The live server is **never rebuilt** — step 6 `tenants fetch` adopts the running deployment
into the new repo shape. `server deploy` after cutover should be a near-noop.

**Risk:** the cutover step. Mitigation — run step 6 with `--dry` first, diff rendered output
against what is actually on the server, proceed only when the diff is empty or understood.
