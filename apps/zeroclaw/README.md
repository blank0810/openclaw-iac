# apps/zeroclaw — ZeroClaw Evaluation

## What is ZeroClaw?

[ZeroClaw](https://github.com/zeroclaw-labs/zeroclaw) is a Rust-based personal
AI assistant runtime, community-built at Harvard / MIT / Sundai.Club. It
reimplements the OpenClaw concept with a focus on security, small footprint
(<5MB RAM), and production hardening.

**Official sources (verified):**
- Repo: <https://github.com/zeroclaw-labs/zeroclaw>
- Website: <https://zeroclawlabs.ai>
- License: Apache-2.0 / MIT dual

**Impersonators to avoid** (per upstream security advisory 2026-02-19):
- `zeroclaw.org`, `zeroclaw.net` — point to a hostile fork
- `openagen/zeroclaw` GitHub org — not us

## Why we're evaluating

The Managed Agents MVP under `apps/slack-agent/` works but has hard limits for
the "plug-and-play client handover" product vision:

- No native scheduling — every client wants "summarize my inbox at 8am"
- Multi-tenant isolation has to be built on top
- Platform maturity uncertain (beta product, moving target)
- Anthropic-only, no provider swap

ZeroClaw promises fixes for all four on paper. This directory is where we
verify that claim before committing.

## What we already know (from upstream docs)

| Capability | Status | Source |
|---|---|---|
| Native cron scheduling | ✅ `zeroclaw cron add/list/remove` | README highlights |
| Slack channel support | ✅ First-class | README channel list |
| Gmail / Calendar via Composio | ✅ Composio is an integrated tool provider | README tools section |
| Salesforce / HubSpot | ❓ Not explicitly listed — may be available via Composio's own catalog | — |
| Multi-tenant (one instance, many users) | ❌ "Personal, single-user assistant" | README |
| Per-tenant instance (one VPS per client) | ✅ Viable — <5MB RAM on $10 hardware | Benchmarks |
| Sandboxing (addresses OpenClaw leaks) | ✅ Workspace isolation, command allowlist, forbidden paths, pairing codes | README security section |
| Provider swap (not Anthropic-only) | ✅ OpenAI-compatible + pluggable endpoints | README |
| Web dashboard | ✅ React 19 + Vite, real-time | README highlights |
| Migration from OpenClaw | ✅ `zeroclaw migrate openclaw` | README |

## Remaining unknowns — to verify hands-on

1. **Salesforce / HubSpot connectors** — is the Composio-backed tool list deep
   enough for the client vision, or do we need to write custom tools?
2. **Slack Bolt / Socket Mode support** — does ZeroClaw's Slack integration
   use the same Slack app we already have configured for `slack-agent/`, or
   does it need different auth?
3. **Cron DSL + reliability** — can we schedule "every weekday 8am Asia/Manila,
   summarize inbox and post to Slack"? Does it survive daemon restarts?
4. **Multi-user workaround ergonomics** — how painful is running N isolated
   ZeroClaw instances on one VPS? Resource accounting? Port collisions?
5. **Onboarding UX** — is `zeroclaw onboard` client-handover-friendly, or does
   it still require a technical operator? (This is the core product question.)

## Install

ZeroClaw installs globally — config lives in `~/.zeroclaw/`, binary at
`/usr/local/bin/zeroclaw` (or equivalent). Our `apps/zeroclaw/` directory only
holds evaluation notes and setup scripts, not runtime state.

```bash
cd apps/zeroclaw
./scripts/install.sh
```

The script installs Rust (if absent) via `rustup`, clones the official
ZeroClaw repo to a temp dir, builds `--release`, installs the binary, and
kicks off `zeroclaw onboard` for guided setup.

## After install — evaluation checklist

Work through these in order, note results in `notes.md` (create as needed):

- [ ] `zeroclaw doctor` — clean bill of health?
- [ ] `zeroclaw status` — gateway + channels up?
- [ ] Connect Slack channel using existing app tokens (Socket Mode)
- [ ] Send test message: "Hello" in DM → get reply
- [ ] Connect Gmail via Composio: "connect my gmail"
- [ ] Schedule test: `zeroclaw cron add "every 1 minute" "send DM: tick"` — does it fire?
- [ ] Security: try to read `/etc/passwd` via agent, verify it's blocked
- [ ] Spin up a second instance with a different workspace dir — do they isolate?

## Decision criteria

After running the checklist, decide:

- **All green** → migrate scheduler/tenant layer from `slack-agent/` to ZeroClaw
- **Mostly green, minor gaps** → stay on Managed Agents for user-facing chat;
  run ZeroClaw alongside for scheduled jobs only
- **Red on multi-instance or Slack integration** → abandon; build our own thin
  scheduler on top of `slack-agent/` with APScheduler
