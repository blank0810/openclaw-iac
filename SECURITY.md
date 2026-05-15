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

Secrets are env-only: `lib/agent_env.py` routes LLM, Slack, and Composio credentials into `zeroclaw.env`, which deploy code chmods to `0600`. `templates/config.toml.j2` renders only non-secret metadata, and `tests/test_no_secrets_in_config.py` fails if known secret values appear in rendered config.

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

Remote object-storage backups are not implemented in this rewrite because the current operating model is a solo-dev single-host deployment. Cron job execution is scaffolded with `agents/<slug>/cron.toml` but not wired because scheduled job management was explicitly deferred from v1.
