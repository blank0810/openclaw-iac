# Agent Ownership (user_id) — Design

**Date:** 2026-05-22
**Status:** Validated, ready for implementation plan
**Scope:** Associate each provisioned agent with an owning `user_id`, persist it,
and echo it (plus key docker info) in the create response. Plain-JSON transport
now; Firebase-JWT decode is a documented future swap, not built here.

## Goal

`POST /agents` carries a required `user_id`. The orchestrator records it on the
agent (durably) and returns `{owner, agent identity, docker handle}` so the
caller knows "this agent is for this user, here's its container."

## Decisions (locked)

1. **Transport:** plain JSON `user_id` field on the request now. The existing
   `verify_request` no-op seam later decodes a Firebase JWT and supplies
   `user_id` from the verified `uid` claim. No JWT decode is built now.
2. **Storage:** persisted in `agents/<slug>/agent.toml` `[identity].user_id`
   (so it survives restarts and is queryable via `load_config`).
3. **Required:** yes — missing/blank `user_id` → `422`.
4. **Response:** ownership + key docker info (not a full `inspect` dump).

## Data model

**`CreateAgentRequest`** (`apps/orchestrator/models.py`) gains:
```python
user_id: str   # required, non-empty, control-char-rejected (like tokens)
```

**`AgentDefinition`** (`lib/config.py`) gains:
```python
user_id: str   # _parse_agent_toml reads identity.get("user_id", "")
```
Legacy agents without the field load with `user_id == ""` (no crash).

**`AgentResult`** (`apps/orchestrator/models.py`) becomes:
```python
user_id: str
name: str
display_name: str        # NEW
container_name: str
container_id: str         # NEW (docker container .id)
image: str                # NEW (image actually run)
server_ip: str
host: str
gateway_port: int
status: str
```

Example success payload:
```json
{
  "user_id": "u_123",
  "name": "dispatch-bot",
  "display_name": "Dispatch",
  "container_name": "zeroclaw-dispatch-bot",
  "container_id": "3f9a1c...",
  "image": "ghcr.io/zeroclaw-labs/zeroclaw:v0.7.3-debian",
  "server_ip": "178.104.222.39",
  "host": "178.104.222.39",
  "gateway_port": 42617,
  "status": "running"
}
```

## Flow (`main.py::create_agent`, ordering unchanged)

1. Pydantic validates body — `user_id` required + control-char-clean (else 422).
2. `active_job_for(slug)` → 409; `docker_client_factory()`; `_container_exists` → 409.
3. `build_agent_definition` writes `agent.toml` incl. `[identity].user_id`.
4. `store.create(slug=...)` → `bg.add_task(provision_agent, …)`.
5. `provision_agent` runs render→chown→network→pull→run, then builds
   `AgentResult` with `user_id` + `display_name` (from the AgentDefinition) +
   `container.id` + the resolved `image`.

## JWT seam (upgrade path — NOT built now)

Today `user_id` is a request-body field and `verify_request` is a no-op. When
Firebase JWT lands, `verify_request` verifies the token and extracts `uid`;
the handler then uses the verified claim as `user_id` (ignoring or requiring a
match with the body). One clearly-commented swap point.

## Ownership querying (future, YAGNI)

Because `user_id` is in `agent.toml`, a future `GET /agents?user_id=` is a
trivial `load_config()` filter. Not built in this slice.

## Error handling

- missing/blank `user_id` → 422
- control-char `user_id` → 422
- all existing 409 / 404 / terminal-failure behavior unchanged

## Testing (TDD, fully mocked — no daemon)

- request: `user_id` omitted → 422; control-char `user_id` → 422.
- `build_agent_definition`: `agent.toml` round-trips `[identity].user_id`;
  `AgentDefinition.user_id` populated.
- `provision_agent`: `AgentResult` carries `user_id`, `display_name`,
  `container_id` (from the fake `container.id`), `image`.
- `_parse_agent_toml`: legacy agent without `user_id` → `""`, no crash.

## Out of scope

- JWT decode/verification (seam only)
- `GET /agents` listing / per-user query
- Auth enforcement (verify_request stays no-op)
- Changing the gateway/runtime
