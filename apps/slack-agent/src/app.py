import json
import logging
import os
import re
import sys
from pathlib import Path

import anthropic
from composio import Composio
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

sys.path.insert(0, str(Path(__file__).parent))
from session_store import SessionStore  # noqa: E402

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("slack-agent")

ANTH = anthropic.Anthropic()


def _resolve_toolkit_versions() -> dict[str, str]:
    """Query Composio for the current version of each toolkit we use.

    Composio's `tools.execute()` requires a pinned version ('latest' is not
    accepted for manual execution). Resolve at import time so the client is
    configured correctly for the lifetime of the process.
    """
    bootstrap = Composio()
    versions: dict[str, str] = {}
    for slug in ("gmail", "googlecalendar"):
        meta = bootstrap.toolkits.get(slug).meta
        versions[slug] = meta.version
    return versions


TOOLKIT_VERSIONS = _resolve_toolkit_versions()
COMP = Composio(toolkit_versions=TOOLKIT_VERSIONS)
AGENT_ID = os.environ["AGENT_ID"]
ENVIRONMENT_ID = os.environ["ENVIRONMENT_ID"]
GMAIL_AUTH_CONFIG_ID = os.environ["GMAIL_AUTH_CONFIG_ID"]
CALENDAR_AUTH_CONFIG_ID = os.environ["CALENDAR_AUTH_CONFIG_ID"]
SESSION_STORE = SessionStore(os.getenv("SESSION_DB_PATH", "./sessions.db"))

app = App(token=os.environ["SLACK_BOT_TOKEN"])
MENTION_RE = re.compile(r"<@[A-Z0-9]+>\s*")


def thread_key(channel: str, thread_ts: str) -> str:
    return f"{channel}:{thread_ts}"


def get_or_create_session(key: str) -> str:
    session_id = SESSION_STORE.get(key)
    if session_id:
        return session_id
    session = ANTH.beta.sessions.create(
        agent=AGENT_ID,
        environment_id=ENVIRONMENT_ID,
        title=f"Slack {key}",
    )
    SESSION_STORE.put(key, session.id)
    log.info("created session %s for %s", session.id, key)
    return session.id


def auth_config_for(slug: str) -> tuple[str, str] | None:
    """Return (auth_config_id, toolkit_name) for a tool slug, or None."""
    if slug.startswith("GMAIL_"):
        return GMAIL_AUTH_CONFIG_ID, "Gmail"
    if slug.startswith("GOOGLECALENDAR_"):
        return CALENDAR_AUTH_CONFIG_ID, "Google Calendar"
    return None


def send_connect_link(
    slack_client,
    channel: str,
    thread_ts: str | None,
    user_id: str,
    toolkit_label: str,
    auth_config_id: str,
) -> str:
    """Generate OAuth URL for user + toolkit, post to Slack. Returns the URL.

    If thread_ts is None (top-level channel mention or DM), the message is
    posted at the same level as the original interaction.
    """
    link_req = COMP.connected_accounts.link(
        user_id=user_id,
        auth_config_id=auth_config_id,
    )
    url = getattr(link_req, "redirect_url", None)
    if not url:
        raise RuntimeError(f"Composio link() returned no redirect_url: {link_req!r}")
    post_kwargs: dict = {
        "channel": channel,
        "text": (
            f"To use {toolkit_label} tools, please authorize here: {url}\n"
            f"Once you've authorized, ask me again and I'll retry."
        ),
    }
    if thread_ts:
        post_kwargs["thread_ts"] = thread_ts
    slack_client.chat_postMessage(**post_kwargs)
    return url


CONNECT_TOOL_MAP = {
    "connect_gmail": ("Gmail", GMAIL_AUTH_CONFIG_ID),
    "connect_google_calendar": ("Google Calendar", CALENDAR_AUTH_CONFIG_ID),
}


def dispatch_tool(
    slug: str,
    payload: dict,
    composio_user_id: str,
    slack_client,
    channel: str,
    thread_ts: str | None,
) -> tuple[str, bool]:
    """Execute a tool via Composio. Returns (result_text, is_error).

    If the user doesn't have a connection for this toolkit, posts an OAuth
    link to the Slack thread and returns a friendly error string that the
    agent can surface.
    """
    # Explicit "connect X" tools — generate link directly, no Composio call
    if slug in CONNECT_TOOL_MAP:
        toolkit_label, auth_config_id = CONNECT_TOOL_MAP[slug]
        try:
            url = send_connect_link(
                slack_client, channel, thread_ts, composio_user_id, toolkit_label, auth_config_id
            )
            return (
                f"OAuth link for {toolkit_label} posted to Slack thread: {url}",
                False,
            )
        except Exception as exc:
            log.exception("connect link failed")
            return f"Failed to generate {toolkit_label} OAuth link: {exc}", True

    ac = auth_config_for(slug)
    if ac is None:
        return f"Unknown tool: {slug}", True
    auth_config_id, toolkit_label = ac

    try:
        resp = COMP.tools.execute(
            slug=slug,
            arguments=payload or {},
            user_id=composio_user_id,
        )
    except Exception as exc:
        msg = str(exc).lower()
        if "connected account" in msg or "no connection" in msg or "not connected" in msg:
            url = send_connect_link(
                slack_client, channel, thread_ts, composio_user_id, toolkit_label, auth_config_id
            )
            return (
                f"User has not connected {toolkit_label}. OAuth link posted to Slack: {url}",
                True,
            )
        log.exception("composio execute failed")
        return f"Error executing {slug}: {exc}", True

    # Composio SDK returns either a dict or a Pydantic model — normalize
    if isinstance(resp, dict):
        successful = resp.get("successful", False)
        err = resp.get("error") or ""
        data = resp.get("data") or {}
    else:
        successful = getattr(resp, "successful", False)
        err = getattr(resp, "error", "") or ""
        data = getattr(resp, "data", {}) or {}

    if not successful:
        if err and (
            "connected account" in err.lower()
            or "no connection" in err.lower()
            or "not connected" in err.lower()
        ):
            url = send_connect_link(
                slack_client, channel, thread_ts, composio_user_id, toolkit_label, auth_config_id
            )
            return (
                f"User has not connected {toolkit_label}. OAuth link posted to Slack: {url}",
                True,
            )
        return f"Tool {slug} failed: {err or 'unknown error'}", True

    return json.dumps(data, default=str)[:8000], False


def run_turn(
    session_id: str,
    user_text: str,
    composio_user_id: str,
    slack_client,
    channel: str,
    thread_ts: str | None,
) -> str:
    chunks: list[str] = []
    first_pass = True

    while True:
        with ANTH.beta.sessions.events.stream(session_id=session_id) as stream:
            if first_pass:
                ANTH.beta.sessions.events.send(
                    session_id=session_id,
                    events=[
                        {
                            "type": "user.message",
                            "content": [{"type": "text", "text": user_text}],
                        }
                    ],
                )
                first_pass = False

            pending: list = []
            terminal = False
            for event in stream:
                etype = getattr(event, "type", None)
                if etype == "agent.message":
                    for block in getattr(event, "content", []) or []:
                        if getattr(block, "type", None) == "text":
                            chunks.append(block.text)
                elif etype == "agent.custom_tool_use":
                    pending.append(event)
                elif etype == "session.status_terminated":
                    terminal = True
                    break
                elif etype == "session.status_idle":
                    stop = getattr(event, "stop_reason", None)
                    if getattr(stop, "type", None) != "requires_action":
                        terminal = True
                    break

        if terminal:
            break
        if not pending:
            log.warning("requires_action with no pending tool calls")
            break

        results = []
        for call in pending:
            slug = getattr(call, "tool_name", None) or getattr(call, "name", None)
            inp = getattr(call, "input", {}) or {}
            log.info("tool call: %s user=%s", slug, composio_user_id)
            text, is_error = dispatch_tool(
                slug, inp, composio_user_id, slack_client, channel, thread_ts
            )
            results.append(
                {
                    "type": "user.custom_tool_result",
                    "custom_tool_use_id": call.id,
                    "content": [{"type": "text", "text": text}],
                    "is_error": is_error,
                }
            )
        ANTH.beta.sessions.events.send(session_id=session_id, events=results)

    return "".join(chunks).strip() or "(no response)"


def handle_user_message(event, client):
    text = event.get("text", "") or ""
    channel = event["channel"]
    user_ts = event["ts"]
    slack_user = event["user"]  # Slack user ID — used as Composio user_id
    incoming_thread_ts = event.get("thread_ts")
    is_dm = event.get("channel_type") == "im"

    clean = MENTION_RE.sub("", text).strip()
    if not clean:
        return

    # Scope session + reply placement based on where the message came from.
    if incoming_thread_ts:
        # Reply in the existing thread; session is continuous within that thread.
        session_key = f"thread:{channel}:{incoming_thread_ts}"
        reply_thread_ts: str | None = incoming_thread_ts
    elif is_dm:
        # DM — one continuous session per user DM channel; flat replies.
        session_key = f"dm:{channel}"
        reply_thread_ts = None
    else:
        # Top-level channel @-mention — reply at channel level (not threaded).
        # Fresh session per mention so unrelated @-mentions don't cross-talk.
        session_key = f"mention:{channel}:{user_ts}"
        reply_thread_ts = None

    post_kwargs: dict = {"channel": channel, "text": "_thinking..._"}
    if reply_thread_ts:
        post_kwargs["thread_ts"] = reply_thread_ts

    placeholder = client.chat_postMessage(**post_kwargs)
    try:
        session_id = get_or_create_session(session_key)
        reply = run_turn(
            session_id, clean, slack_user, client, channel, reply_thread_ts
        )
        client.chat_update(channel=channel, ts=placeholder["ts"], text=reply)
    except Exception as exc:
        log.exception("turn failed")
        client.chat_update(
            channel=channel,
            ts=placeholder["ts"],
            text=f"Error: `{exc}`",
        )


@app.event("app_mention")
def on_mention(event, client):
    handle_user_message(event, client)


@app.event("message")
def on_message(event, client):
    if event.get("channel_type") != "im":
        return
    if event.get("subtype") or event.get("bot_id"):
        return
    handle_user_message(event, client)


if __name__ == "__main__":
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()
