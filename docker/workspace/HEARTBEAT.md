# HEARTBEAT.md - Periodic Checks

When you receive a heartbeat poll, rotate through these checks (don't do all every time — pick 2-3 per heartbeat):

## Priority Checks
- **Emails** — Any urgent unread messages? (via Composio Gmail)
- **Calendar** — Upcoming events in the next 24 hours? (via Composio Calendar)

## Routine Checks
- **Memory maintenance** — Review recent daily memory files, update MEMORY.md with anything worth keeping long-term
- **Channel health** — Are all enabled channels still connected?

## Quiet Hours
- Between 23:00-07:00 (user's timezone), reply HEARTBEAT_OK unless something is urgent
- If nothing needs attention, reply HEARTBEAT_OK

## Notes
- Scheduled tasks (daily digests, reminders) use the built-in `cron` tool — NOT Composio/Supabase (Composio's Supabase toolkit is for project admin, not scheduling)
- Use Composio MCP tools for email and calendar checks
- Don't check services that aren't connected yet — skip if the Composio integration isn't authenticated
