# Title

[Bug]: Slack Socket Mode adapter silently zombies — no client ping, no read deadline, no health-registry signal

# Body

## Summary

ZeroClaw's Slack Socket Mode adapter can sit on a half-dead websocket indefinitely after a normal-looking `websocket connected`. The container reports `healthy`, the bot logs nothing, and Slack-delivered events disappear from the bot's perspective until a manual `docker restart`.

## Repro

1. Run `ghcr.io/zeroclaw-labs/zeroclaw:v0.7.3-debian` with Slack Socket Mode enabled, against a low-traffic workspace.
2. Wait 12+ hours.
3. Observe `docker logs`: a normal `Slack Socket Mode: websocket connected` line, then **multi-hour silence** with zero further log activity (no server-pong, no `disconnect`, no read error). Slack-side, message delivery to that socket has stopped; the bot never notices.
4. `docker restart` recovers immediately.

In our deployment we observed a **20-hour silent gap** between two `websocket connected` lines, while Slack's normal Socket Mode rotation is ~5h — so multiple expected `disconnect` events never arrived, and the read loop never returned an error.

## Root cause (code-level)

`crates/zeroclaw-channels/src/slack.rs::listen_socket_mode` at L2596–L2619:

- L2600: `while let Some(frame) = read.next().await` — bare await, **no read timeout**.
- L2603–L2609: only **responds** to server pings (`Ping → Pong`). Never sends a client-initiated ping.
- L2615–L2618: error path covers explicit read errors, but on a zombie TCP path (e.g. NAT idle-timeout, stateful firewall drop) the kernel sees no FIN/RST, so `read.next()` blocks forever and the error branch is unreachable.
- The underlying stream is opened via `zeroclaw_config::schema::ws_connect_with_proxy` (L2573) — `SO_KEEPALIVE` is not configured, so the kernel never probes either.

Additionally, the Slack adapter is **the only channel that doesn't write to the health registry**: `crates/zeroclaw-channels/src/orchestrator/mqtt.rs` calls `zeroclaw_runtime::health::mark_component_ok("mqtt")` at L60 and L79; `slack.rs` has no equivalent. Consequently `GET /api/health` (`crates/zeroclaw-gateway/src/api.rs` L789) is structurally blind to Slack-channel liveness — it can't surface this failure to compose healthchecks or external watchdogs.

## Suggested fix

In `listen_socket_mode`:

1. Wrap `read.next()` in `tokio::time::timeout(Duration::from_secs(60), …)`. On timeout, send `WsMessage::Ping(b"heartbeat")`, then expect a Pong within ~30s; on miss, `break` to fall through the existing reconnect path.
2. On every successful frame, call `zeroclaw_runtime::health::mark_component_ok("slack")`. On `break`, call `mark_component_error` (mirroring the MQTT adapter's pattern at `mqtt.rs:60,79`). This makes `GET /api/health` a load-bearing signal for Slack-channel liveness.
3. Optionally, set `SO_KEEPALIVE` on the underlying TCP stream as defense-in-depth.

Slack's official Python SDK defaults to a 5-second pong timeout client-side ([slack-sdk Socket Mode reference](https://docs.slack.dev/tools/python-slack-sdk/reference/socket_mode/websocket_client/)). Bringing the Rust adapter to parity closes the gap.

## References

- [Slack — Using Socket Mode](https://docs.slack.dev/apis/events-api/using-socket-mode/)
- [slack-sdk (Python) Socket Mode websocket_client — 5s default pong timeout](https://docs.slack.dev/tools/python-slack-sdk/reference/socket_mode/websocket_client/)
- [bolt-js #2496 — pong timeout in Socket Mode](https://github.com/slackapi/bolt-js/issues/2496)
- [WebSocket.org — Fix WebSocket Timeout and Silent Dropped Connections](https://websocket.org/guides/troubleshooting/timeout/)
