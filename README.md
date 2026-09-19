# Star Wars Server Announcement Bot by Superluks5

A Discord bot with a `/announce` slash command. Anyone with permission can
type `/announce`, fill in a short form, and the bot polishes the text with
Groq's free AI API, formats it using your server template, and posts it.

## Setup

1. **Create the Discord bot:**
   - Go to https://discord.com/developers/applications
   - New Application → give it a name → go to "Bot" tab → "Reset Token" → copy it
   - Under "Privileged Gateway Intents" you don't need to enable anything extra for this bot
   - Go to "OAuth2 → URL Generator", check `bot` and `applications.commands` scopes,
     under permissions check `Send Messages` and `Use Slash Commands`, then use the
     generated URL to invite the bot to your server

2. **Get a free Groq API key:**
   - Sign up at https://console.groq.com (no credit card needed)
   - Create an API key

3. **Configure:**
   - Rename `.env.example` to `.env`
   - Fill in `DISCORD_TOKEN`, `GROQ_API_KEY`, and `SERVER_NAME`
   - `GUILD_ID` is optional and keeps one legacy/primary server registered;
     additional servers are loaded from the approved-server registry
    - The dashboard approval link grants Administrator by default. Set
       `BOT_INVITE_PERMISSIONS` to a different permissions integer if the public
       bot should use narrower permissions. The link identifies the bot directly
       from `DISCORD_TOKEN`, so it will not accidentally invite a DEV bot.

4. **Install and run:**
   ```
   pip install -r requirements.txt
   python bot.py
   ```

5. In Discord, type `/announce` in any channel the bot can see. A form pops up
   asking for your draft, announcement number, name, and rank. You'll get a
   preview with a "Post to channel" button before anything goes live.

When a server access request is approved in the dashboard, the server
administrator receives a DM with a bot invite link. Discord requires that
administrator to click the link and authorize the bot; the bot token cannot
accept an invite silently. After the authorization completes, the bot stays
in the approved server instead of leaving again. On startup, slash commands
are synced separately to the primary server and every approved server.

## Hosting it 24/7

Running `python bot.py` on your own PC only works while your PC is on.
For an always-on bot, deploy this folder to a free host like Railway,
Render, or an Oracle Cloud free-tier VM. Set the same environment variables
(`DISCORD_TOKEN`, `GROQ_API_KEY`, `SERVER_NAME`) in the host's dashboard
instead of using the `.env` file.

## Adding more commands later

This bot uses a "cogs" structure — every command lives in its own file inside
the `cogs/` folder, and `bot.py` loads all of them automatically on startup.

To add a new command:
1. Create a new file in `cogs/`, e.g. `cogs/rules.py`
2. Follow the same pattern as `cogs/announce.py` (a `commands.Cog` class with
   an `@app_commands.command(...)` method, plus an `async def setup(bot)` at
   the bottom)
3. Restart the bot — it picks up the new file automatically, no other code
   needs to change

Some ideas for future commands: `/rules`, `/event` (event announcements),
`/rank` (assign roles), `/poll`, `/welcome` (custom welcome messages).
