#!/usr/bin/env python3
"""Create environment + agent. Fetches Gmail/Calendar tool schemas from Composio
and declares them as custom tools on the agent — the orchestrator executes them
via Composio's API when `agent.custom_tool_use` events fire.

Re-running always creates a fresh agent (paste the new AGENT_ID into .env).
Reuses ENVIRONMENT_ID if already set in .env.
"""
import os

import anthropic
from composio import Composio
from dotenv import load_dotenv

load_dotenv()

anth = anthropic.Anthropic()
comp = Composio()

# Curated tool set. Trimmed to the highest-leverage slugs so the agent isn't
# drowning in 50+ options. Slugs match Composio's canonical toolkit actions.
CURATED_TOOL_SLUGS = [
    "GMAIL_FETCH_EMAILS",
    "GMAIL_SEND_EMAIL",
    "GMAIL_CREATE_EMAIL_DRAFT",
    "GMAIL_REPLY_TO_THREAD",
    "GOOGLECALENDAR_LIST_CALENDARS",
    "GOOGLECALENDAR_EVENTS_LIST",
    "GOOGLECALENDAR_CREATE_EVENT",
    "GOOGLECALENDAR_FIND_EVENT",
    "GOOGLECALENDAR_UPDATE_EVENT",
    "GOOGLECALENDAR_DELETE_EVENT",
]

SYSTEM_PROMPT = (
    "You are a helpful assistant reachable via Slack. "
    "You have access to a sandboxed Linux environment with bash, file "
    "operations, glob/grep, and web search/fetch. You also have access "
    "to the user's Gmail and Google Calendar via custom tools named "
    "GMAIL_* and GOOGLECALENDAR_*.\n\n"
    "If the user says anything like 'connect my gmail', 'authorize "
    "gmail', 'link my calendar', etc., use the `connect_gmail` or "
    "`connect_google_calendar` tool to generate an authorization link. "
    "The tool posts the link to Slack for them. After calling it, just "
    "tell the user the link has been posted and to click it.\n\n"
    "If a Gmail/Calendar tool call returns an error about the user not "
    "being connected, tell them to click the link we posted and retry "
    "— don't retry the tool automatically.\n\n"
    "Keep responses concise and direct — Slack is a chat medium. For "
    "multi-step work, narrate progress briefly. For calendar timestamps, "
    "use RFC3339 format; infer the user's timezone from context, and ask "
    "if unclear."
)

CONNECT_TOOLS = [
    {
        "type": "custom",
        "name": "connect_gmail",
        "description": (
            "Generate an OAuth authorization link for the user to connect "
            "their Gmail account to this assistant. The link is posted to "
            "the current Slack thread. Call this when the user asks to "
            "connect, authorize, link, or grant access to Gmail."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "type": "custom",
        "name": "connect_google_calendar",
        "description": (
            "Generate an OAuth authorization link for the user to connect "
            "their Google Calendar account. The link is posted to the "
            "current Slack thread. Call this when the user asks to "
            "connect, authorize, link, or grant access to Calendar."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


def _sanitize_schema(schema: dict) -> dict:
    """Keep only fields Anthropic's custom-tool input_schema accepts."""
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}
    allowed_root = {"type", "properties", "required", "additionalProperties"}
    out = {k: v for k, v in schema.items() if k in allowed_root}
    out.setdefault("type", "object")
    # Recursively sanitize nested property schemas — strip title, description,
    # default, examples, $schema, $id, etc. from each property.
    props = out.get("properties") or {}
    if isinstance(props, dict):
        out["properties"] = {
            name: _sanitize_property(p) for name, p in props.items()
        }
    return out


def _sanitize_property(prop: object) -> dict:
    if not isinstance(prop, dict):
        return {"type": "string"}
    allowed = {"type", "enum", "items", "properties", "required", "additionalProperties"}
    keep = {k: v for k, v in prop.items() if k in allowed}
    if "items" in keep and isinstance(keep["items"], dict):
        keep["items"] = _sanitize_property(keep["items"])
    if "properties" in keep and isinstance(keep["properties"], dict):
        keep["properties"] = {
            n: _sanitize_property(p) for n, p in keep["properties"].items()
        }
    return keep


def fetch_tool_schemas(slugs: list[str]) -> list[dict]:
    """Fetch tool definitions from Composio, convert to Anthropic custom tool shape."""
    raw = comp.tools.get_raw_composio_tools(tools=slugs)
    out = []
    found_slugs = set()
    for tool in raw:
        slug = getattr(tool, "slug", None) or getattr(tool, "name", None)
        if not slug:
            continue
        found_slugs.add(slug)
        description = getattr(tool, "description", "") or ""
        schema = getattr(tool, "input_parameters", None) or {
            "type": "object",
            "properties": {},
        }
        out.append(
            {
                "type": "custom",
                "name": slug,
                "description": description[:1000],
                "input_schema": _sanitize_schema(schema),
            }
        )
    missing = set(slugs) - found_slugs
    if missing:
        print(f"  Warning: missing slugs (not registered): {sorted(missing)}")
    return out


def main() -> None:
    env_id = os.getenv("ENVIRONMENT_ID")
    if env_id:
        print(f"Reusing environment: {env_id}")
    else:
        print("Creating environment...")
        environment = anth.beta.environments.create(
            name="slack-agent-env",
            config={
                "type": "cloud",
                "networking": {"type": "unrestricted"},
            },
        )
        env_id = environment.id
        print(f"  created: {env_id}")

    print(f"Fetching {len(CURATED_TOOL_SLUGS)} tool schemas from Composio...")
    custom_tools = fetch_tool_schemas(CURATED_TOOL_SLUGS)
    print(f"  got {len(custom_tools)} tools")

    tools = [
        {
            "type": "agent_toolset_20260401",
            "default_config": {
                "enabled": True,
                "permission_policy": {"type": "always_allow"},
            },
        },
        *CONNECT_TOOLS,
        *custom_tools,
    ]

    existing_id = os.getenv("AGENT_ID")
    if existing_id:
        print(f"Updating existing agent {existing_id}...")
        current = anth.beta.agents.retrieve(existing_id)
        agent = anth.beta.agents.update(
            existing_id,
            version=current.version,
            name="Slack Assistant",
            model="claude-opus-4-7",
            system=SYSTEM_PROMPT,
            tools=tools,
        )
        print(f"  updated: {agent.id} (now version {agent.version})")
        print("\nAGENT_ID unchanged — .env already correct.")
    else:
        print("Creating agent...")
        agent = anth.beta.agents.create(
            name="Slack Assistant",
            model="claude-opus-4-7",
            system=SYSTEM_PROMPT,
            tools=tools,
        )
        print(f"  created: {agent.id}")
        print("\nPaste into slack-agent/.env:")
        print(f"ENVIRONMENT_ID={env_id}")
        print(f"AGENT_ID={agent.id}")


if __name__ == "__main__":
    main()
