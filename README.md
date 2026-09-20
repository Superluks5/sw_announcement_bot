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
    - `DISCORD_CLIENT_ID` and `DISCORD_CLIENT_SECRET` must come from the same
       Discord Developer Portal application as `DISCORD_TOKEN`; do not use a
       DEV bot application's OAuth credentials for the dashboard.
   - `GUILD_ID` is optional and keeps one legacy/primary server registered;
     additional servers are loaded from the approved-server registry
   - The dashboard approval link grants Administrator by default. Set
     `BOT_INVITE_PERMISSIONS` to a different permissions integer if the public
     bot should use narrower permissions. The link identifies the bot directly
     from `DISCORD_TOKEN`, so it will not accidentally invite a DEV bot.
    - `REVIEW_INVITE_MAX_AGE` controls Owner Panel review invites in seconds;
       it defaults to 86400 (24 hours). Set it to `0` only when permanent review
       invites are explicitly required.

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

The Owner Panel periodically discovers servers containing the bot, records a
review snapshot, and creates a temporary review invite when Discord permits
it. The dashboard health check is available at `/health`; Owner Panel users
can also create a database backup from the overview page.

For production HTTPS deployments, set `DASHBOARD_COOKIE_SECURE=1` and serve
the Flask dashboard behind Nginx or another production reverse proxy. Bot
Control is restricted to Owner Panel users; normal server administrators
cannot restart the bot or dashboard services.

## Oracle VM operations

The `ops/` directory contains deployment support. Install `ops/swbot-monitor.service`
and `ops/swbot-monitor.timer` under `/etc/systemd/system/`, then run:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now swbot-monitor.timer
```

Run `./ops/backup.sh` for a dated backup outside the project. The backup uses
SQLite's online backup API and a lock, so concurrent backups cannot corrupt
the archive. Deploy with `./ops/update.sh`; it requires a clean Git worktree,
creates and verifies a backup, pulls `origin/main`, runs tests, restarts
services, and rolls back the Git revision if `/health` fails.

Use `./ops/restore-test.sh /var/backups/swbot/swbot-<timestamp>.tar.gz` to
validate a backup's SQLite integrity and runtime JSON before restoring it.
See [RECOVERY.md](RECOVERY.md) for restoration, emergency shutdown, monitoring
simulation, and Gunicorn/Nginx procedures.

For production dashboard serving, install Gunicorn from `requirements.txt`,
use the updated `dashboard/swbot-dashboard.service`, and configure
`ops/swbot-nginx.conf` with your hostname and Let’s Encrypt certificate paths.
Keep `.env`, backups, databases, logs, and `guild_data/` outside Git.

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

## Trust, branding, and privacy

This repository is licensed under `AGPL-3.0-or-later`. The bot commands,
permission checks, dashboard routes, and approval flow are public so server
owners can inspect them. The official hosted bot is identified by its Discord
application, this repository, and its release history.

Forks and self-hosted instances are allowed, but they must use their own
Discord application and token. Do not copy the official bot name, logo, or
identity in a way that could make users believe a fork is the official
instance. See [SECURITY.md](SECURITY.md) for the security model and reporting
process.

Private deployment material includes `.env`, API keys, OAuth secrets, the
dashboard secret, production databases, runtime data, logs, and webhooks.
Those files configure an installation; they do not contain hidden bot
commands or secret access paths.
