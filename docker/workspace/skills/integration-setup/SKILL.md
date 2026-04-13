---
name: integration-setup
description: Help users connect integrations (Gmail, Calendar, Trello) via Composio MCP
---

# Integration Setup

Help users connect third-party integrations. You can register MCP servers in your own config via the `gateway` tool, then restart to activate them.

## Important

- **Before any `config.patch`**, call `config.get` first to retrieve the current config and its `baseHash`.
- **After adding MCP servers**, you MUST call `gateway restart` -- MCP changes are not hot-reloaded.
- **Security note**: API keys provided via chat are stored as literal values in your config. Advise users to provide keys via DM, not in group channels.

## Composio Setup (Gmail, Calendar, Trello)

Composio provides managed OAuth for Google and Trello services. One API key unlocks all of them.

When someone says "set up integrations", "connect my email", "add gmail", "connect calendar", "connect trello", or provides a Composio API key:

**If they DON'T have a Composio API key:**
1. Tell them: "You'll need a Composio API key. Go to https://app.composio.dev, sign up (free tier available), and copy your API key from the dashboard."
2. Wait for the key.

**If they HAVE a key (or just pasted one):**
1. Validate format: Composio keys are typically alphanumeric strings.
2. Use `config.patch` to register the Composio MCP server (one server handles all services):
   ```json
   {
     "mcp": {
       "servers": {
         "composio": {
           "url": "https://connect.composio.dev/mcp",
           "transport": "streamable-http",
           "headers": {
             "x-consumer-api-key": "<THE_LITERAL_KEY>"
           }
         }
       }
     }
   }
   ```
3. Call `gateway restart` to activate the MCP servers.
4. Say: "MCP servers registered and gateway restarting. Now you need to connect your accounts."

## Connecting Individual Services

After the Composio API key is configured, users need to authenticate each service:

**Gmail:**
1. User says "connect my gmail"
2. Use the Composio MCP tools to initiate a connection for Gmail.
3. If the MCP provides an auth URL, send it to the user: "Click this link to authorize Gmail access."
4. After authorization: "Gmail connected! Try asking me to check your emails."

**Google Calendar:**
1. Same flow as Gmail but for Calendar.
2. "Click this link to authorize Calendar access."
3. After authorization: "Calendar connected! Try 'what's on my calendar today?'"

**Trello:**
1. User says "connect trello"
2. Same flow via Composio.
3. After authorization: "Trello connected! Try 'show my trello boards.'"

## Brave Search API Key

When someone says "set up web search", "add brave search", or provides a Brave API key:

1. If they don't have one: "Go to https://brave.com/search/api and sign up (free: 2000 queries/month). Copy your API key."
2. With the key: This is an environment variable, not an MCP server. Tell the user: "Brave Search requires the API key in the server environment. Ask the server operator to add `BRAVE_API_KEY=<key>` to the `.env` file and restart the container."
3. If Brave is not configured, web search falls back to Gemini grounding (which works with your existing Gemini API key).

## OpenAI (Image Generation)

When someone asks about image generation:

1. If `OPENAI_API_KEY` is not set: "Image generation needs an OpenAI API key in the server environment. Ask the operator to add `OPENAI_API_KEY=<key>` to `.env` and restart."
2. If it is set: image generation works via the `image_generate` tool automatically.

## Status Check

When someone asks "what integrations are connected?" or "integration status":

1. Use `config.get` to check for `mcp.servers` entries.
2. Report which MCP servers are registered and active.
