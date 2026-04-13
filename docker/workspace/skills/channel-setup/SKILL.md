---
name: channel-setup
description: Guide users through connecting messaging channels (Telegram, Discord, WhatsApp)
---

# Channel Setup

Help users connect new messaging channels. You have the `gateway` tool which lets you modify your own config via `config.patch`.

## Important

- **Before any `config.patch`**, call `config.get` first to retrieve the current config and its `baseHash`. Pass the `baseHash` with your `config.patch` call to prevent conflicts.
- **Security note**: Tokens provided via chat are stored as literal values in your config file (not environment variables). This is fine for personal/dev use. For production, advise users to add tokens to the server `.env` file instead.

## Telegram

When someone says "connect telegram" or similar:

**If they DON'T have a token:**
1. Tell them: "Open Telegram, search for @BotFather, send `/newbot`, follow the prompts, and paste the token here."
2. Wait for the token.

**If they HAVE a token (or just pasted one):**
1. Validate format: Telegram tokens look like `123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` (numeric ID, colon, 35 alphanumeric chars).
2. Use the gateway tool to run `config.patch` with:
   ```json
   {
     "channels": {
       "telegram": {
         "enabled": true,
         "botToken": "<THE_LITERAL_TOKEN>",
         "dmPolicy": "open",
         "allowFrom": ["*"]
       }
     }
   }
   ```
3. Wait ~10 seconds for hot-reload, then say: "Telegram is connected! Try sending a message to your bot on Telegram to test."

## Discord

When someone says "connect discord" or similar:

**If they DON'T have credentials:**
1. Guide them:
   - "Go to https://discord.com/developers/applications and create a New Application."
   - "Go to Bot tab, click Reset Token, copy the **Bot Token**."
   - "Enable these Privileged Gateway Intents: MESSAGE CONTENT, SERVER MEMBERS, PRESENCE."
   - "Go to OAuth2 > URL Generator, select `bot` scope + permissions: Send Messages, Read Message History, Add Reactions, Use Slash Commands."
   - "Copy the generated URL, open it, and invite the bot to your server."
   - "I also need your **Server ID** (right-click server > Copy Server ID) and your **Discord User ID** (Settings > Advanced > Developer Mode, then right-click yourself > Copy User ID)."
2. Wait for: bot token, server ID, owner user ID.

**If they HAVE all three:**
1. Validate: Discord bot tokens are ~70 chars, server/user IDs are numeric snowflakes (17-20 digits).
2. Use the gateway tool to run `config.patch` with:
   ```json
   {
     "channels": {
       "discord": {
         "enabled": true,
         "token": "<BOT_TOKEN>",
         "dmPolicy": "open",
         "allowFrom": ["<OWNER_ID>"],
         "guilds": {
           "<SERVER_ID>": {
             "requireMention": true,
             "users": ["<OWNER_ID>"]
           }
         }
       }
     }
   }
   ```
3. Say: "Discord is connected! Try mentioning me in your server or sending me a DM."

## WhatsApp

When someone says "connect whatsapp" or similar:

1. Explain: "WhatsApp uses QR code pairing -- I can enable it in my config, but the QR scan needs to be done from the server terminal by an operator."
2. Use the gateway tool to run `config.patch` with:
   ```json
   {
     "channels": {
       "whatsapp": {
         "enabled": true,
         "dmPolicy": "open",
         "allowFrom": ["*"]
       }
     }
   }
   ```
3. Tell the user: "I've enabled WhatsApp in my config. The server operator needs to complete the QR pairing from the server terminal. Ask them to run the WhatsApp login command via `docker exec` and scan the QR code with the phone that should be linked (WhatsApp > Linked Devices > Link a Device)."
4. Say: "Once the QR scan is done and the container restarts, I'll be reachable on WhatsApp."

## Other Channels (Matrix, Teams, LINE, Google Chat)

If someone asks about channels not listed above:

1. Say: "That channel isn't pre-configured yet, but I can look into what's needed."
2. Note: Matrix, Teams, LINE, and Google Chat require plugins and/or inbound webhooks (public URL + reverse proxy). These need infrastructure changes beyond what I can do from chat.
3. Suggest they check with the server operator.

## Disconnecting a Channel

When someone says "disconnect telegram", "disable discord", etc.:

1. Use `config.patch` to set the channel's `enabled` to `false`:
   ```json
   { "channels": { "<channel>": { "enabled": false } } }
   ```
2. Confirm: "Done -- <channel> is now disabled. Your credentials are still saved, so you can re-enable it anytime."

## Status Check

When someone asks "what channels are connected?" or "channel status":

1. Use the gateway tool to call `config.get` to read current channel config.
2. Report which channels are enabled/disabled, and which have tokens configured.
