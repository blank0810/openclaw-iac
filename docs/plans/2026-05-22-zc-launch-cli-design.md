# `zc` — Orchestrator API Launch CLI (Design)

**Date:** 2026-05-22
**Status:** Validated, implementing (MVP)
**Scope:** A thin client CLI over the deployed orchestrator API. Run one
command to create an agent (via `POST /v1/agent/create`) and then drop into its
ZeroClaw terminal chat (TUI). No new server-side behavior.

## Goal

Replace the manual Postman dance (open tunnel → POST → poll → ssh → docker
exec) with a single command:

```
zc launch --name acme --user-id u_adam
```

→ creates the agent via the API, polls to completion, then offers to chat.

## Connectivity

The API only listens on `127.0.0.1:8000` on Server 3. The CLI **auto-manages
an SSH tunnel** for the HTTP calls, then closes it before handing over the
interactive TTY for chat (chat is a separate direct `ssh -t`).

Config (`server_host`, `deploy_user`, `ssh_port`, `deploy_ssh_key_path`) comes
from `lib.config.load_config()` — same `.env`, same SSH shape as
`lib/agents.py:_ssh_base`. The client imports nothing from the Pyinfra/gevent
stack.

## Commands

| Command | Purpose |
|---|---|
| `zc launch --name X --user-id Y [opts]` | create via API + poll + offer chat |
| `zc chat --name X` | re-attach to an already-running agent's TUI (no API) |

### `launch` flow

```
1. gather + validate inputs   (client-side, before any network)
2. open SSH tunnel            ssh -N -L 127.0.0.1:8000:127.0.0.1:8000 ...
3. wait for :8000             poll socket connect, ~10s timeout
4. POST /v1/agent/create      → {job_id}
5. poll GET /v1/agent/job/{id} every 2s until succeeded/failed (~5m timeout)
6. print result               user_id, name, container_name, container_id,
                              image, status
7. prompt                     "Chat with <name> now? [y/N]"
8. if yes                     close tunnel, then
                              ssh -t ... "docker exec -it zeroclaw-<slug> zeroclaw agent"
9. finally                    tunnel always torn down
```

## Inputs

Required: `--name` (validated against `SLUG_PATTERN`), `--user-id` (non-empty).
Optional: `--display-name` (defaults to name).

Slack/Composio activation mirrors `zeroclawctl agents create`:
- bare `--slack` → hidden `getpass` prompts for bot/app tokens + channel id
- passing any `--slack-*` flag activates Slack but skips the prompt
- bare `--composio` → hidden prompt for mcp key; `--composio-mcp-key` skips it
- `--llm-provider` / `--llm-model` optional

Secrets via `getpass` (never echoed, never in shell history, never logged).
Token prefix warnings (`xoxb-`/`xapp-`/`ck_`) match the existing tool. The CLI
ships no token defaults; omitted fields inherit from `agents/_defaults.toml`
server-side.

## Components (`apps/orchestrator/client.py`)

Pure/testable units:
- `build_payload(args) -> dict` — args → `CreateAgentRequest` JSON
- `validate_inputs(name, user_id) -> list[str]` — slug + non-empty checks
- `open_tunnel(cfg) -> Popen` / `wait_for_port(host, port, timeout) -> bool` / `close_tunnel(proc)`
- `create_agent(base_url, payload, session) -> str` — POST, returns job_id
- `poll_job(base_url, job_id, session, *, interval, timeout) -> dict` — loop to terminal
- `chat(cfg, slug, *, runner=subprocess.run) -> int` — `ssh -t` docker exec
- `cmd_launch(args) -> int` / `cmd_chat(args) -> int` / `main(argv) -> int`

`session` and `runner` are injected so tests never touch network/SSH.

## Error handling

| Failure | Behavior |
|---|---|
| Bad slug / empty user_id | print error, exit 1, **before** tunnel opens |
| Tunnel never comes up | print error, exit 1 |
| POST 409 (dup) / 422 (bad) | print server `detail`, exit 1 |
| Job ends `failed` | print error + step states, exit 1 |
| Poll timeout | print last state, exit 1 |
| Chat exec nonzero | print manual fallback cmd + likely cause (read-only rootfs / UID 65534); don't crash |

Tunnel teardown is in a `finally` so it closes on every path.

## Testing (TDD, mocked — no live server)

- `build_payload` / `validate_inputs` — pure unit tests (minimal, +slack, +composio, +llm, bad inputs)
- `create_agent` / `poll_job` — injected fake session (202→job_id; poll succeeds; poll fails; timeout)
- `wait_for_port` — mock socket
- `chat` — injected runner asserts `ssh -t ... docker exec -it zeroclaw-<slug> zeroclaw agent`
- `cmd_launch` — everything mocked: tunnel opened before POST, closed in `finally` even on error; chat declined → no exec; chat accepted → exec called

**Create-boundary:** no test fires a real `POST /v1/agent/create`. The first live
`zc launch` is the operator's action. See memory `feedback-agent-creation-is-operator`.

## Out of scope (YAGNI)

- Auth (API is no-op auth for MVP)
- Persistent config / multi-host / agent list / remove (exist in Pyinfra `zeroclawctl` or later)
- Tunnel reuse across invocations
