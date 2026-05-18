# Cloudesk ZeroClaw Security Implementation

This document maps the ZeroClaw infrastructure rewrite to the agent security checklist.

## 1. Agent Identity

Agent identity is rendered from `templates/workspace/IDENTITY.md.j2` and related workspace templates. `templates/workspace/AGENTS.md.j2` includes a managed security policy placeholder, and `lib/managed_policy.py` replaces that block on every agent deploy while preserving agent-specific notes outside it.

## 2. Customer Isolation

Each agent has isolated remote state under `/opt/zeroclaw/states/<slug>/`. `templates/docker-compose.yml.j2` renders one service and one bridge network (`zc-<slug>`) per enabled agent, with separate `zeroclaw.env`, `config.toml`, and workspace mounts.

## 3. Server Hardening

`lib/bootstrap_prepare.py` creates the deploy user, installs Docker, configures UFW and fail2ban, and keeps ports 22 and 2222 open during bootstrap. `lib/bootstrap_hardening.py` installs an sshd drop-in, disables root/password SSH, restarts `ssh.socket`, and removes port 22 after deploy-key access is verified.

## 4. Tool Permissions

Agent config exposes `composio.allowed_tools`, `policy.denied_domains`, `policy.require_approval_for`, and an `exec.enabled` gate. When exec is enabled, `templates/config.toml.j2` can render deny patterns from `lib/config_patch.py`.

## 5. Secrets

Secrets are split across two surfaces according to what upstream ZeroClaw actually reads at startup (`apps/zeroclaw/upstream/crates/zeroclaw-config/src/schema.rs::apply_env_overrides`):

- **LLM provider key** (Anthropic / LiteLLM): rendered into `zeroclaw.env` as `ZEROCLAW_API_KEY` by `lib/agent_env.py`. Deploy code chmods the file to `0600`. Upstream reads this from environment.
- **Slack tokens** (`bot_token`, `app_token`, `signing_secret`): rendered into `states/<slug>/config.toml`'s `[channels_config.slack]` block by `templates/config.toml.j2`. Upstream has **no** env-read path for these — config-only.
- **Composio API key** (native path) or **MCP x-consumer-api-key** (MCP path): rendered into `[composio].api_key` or `[[mcp.servers]].headers` in `config.toml`. Same reason — upstream doesn't read them from env.

The deploy host's `states/<slug>/config.toml` is owned by the deploy user and chmod-ed to `0600`. The compose mount is `:ro`, so even ZeroClaw's own `Config::save()` can't rewrite it after boot.

Locally, secrets live in `agents/<slug>/agent.toml` and the optional `agents/_defaults.toml`. Both files must be chmod-ed to `0600`. The `agents/` directory is gitignored (only `agents/_template/` is exempted), so neither file lands in git history. Per-agent files override `_defaults.toml` via deep merge (see `lib/config.py::_deep_merge`); shared fields like the Anthropic key, Composio MCP URL, and the autonomy `auto_approve` list typically live in `_defaults.toml`, while per-Slack-app tokens stay per-agent.

`tests/test_no_secrets_in_config.py` enforces this exact split: the LLM key must never appear in rendered `config.toml`, and Slack/Composio tokens must be present in `config.toml` (because that's the only place upstream reads them). `tests/test_agent_env.py` enforces the inverse for the env dict.

## 6. Memory And Privacy

Each agent has its own workspace directory and session storage under its state directory. `lib/workspace.py` supports read-only status, explicit fetch/deploy, and `session-clear`, which archives remote session JSONL files before restarting the agent container.

## 7. Approval And Safety

`policy.require_approval_for` is rendered into config and into the managed AGENTS.md policy block. The managed block instructs the agent to refuse credential disclosure, forbidden filesystem reads, environment enumeration, and approval bypass requests.

## 8. Logging And Audit

The compose template uses bounded Docker `json-file` logs. `lib/audit.py` formats operator audit events as JSONL for `/opt/zeroclaw/audit.log`, and `lib/slack_probe.py` installs per-agent Slack liveness timers that log probe and restart events.

## 9. Backup And Recovery

`lib/backup.py` pulls `config.toml` and `workspace/` into local `backups/<agent>/<timestamp>.tar.gz`, explicitly excluding `zeroclaw.env`. `lib/agents.py` provides fetch, remove-with-archive, and restore commands around `/opt/zeroclaw/states` and `/opt/zeroclaw/.archive`.

## 10. Testing And Cost

The rewrite adds pytest coverage for config validation, template rendering, no-secret rendering, managed policy injection, agent/workspace command boundaries, backup, and server deploy decision logic. Pyinfra deploy files are parse-checked locally and should be verified with `zeroclawctl server deploy --dry` once the live agent is migrated to the new schema. Cost routing remains an agent-level LLM provider/model decision, including direct Anthropic or LiteLLM routing.

## Explicit N/A

Remote object-storage backups are not implemented in this rewrite because the current operating model is a solo-dev single-host deployment.

Scheduled jobs are agent-managed in v1: the ZeroClaw runtime exposes `cron_add`/`cron_list`/`cron_remove`/`cron_run`/`cron_update` tools to the agent at chat time (see upstream `crates/zeroclaw-runtime/src/tools/cron_*.rs`). Operator-authored cron — a git-tracked `cron.json` reconciled to the runtime store via SSH, comparable to the nanobot pattern — is deferred to a future phase, at which point `lib/cron.py` and a per-agent `cron.json` will be introduced.
