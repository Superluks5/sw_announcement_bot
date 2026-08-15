"""
Star Wars Server Bot - Main Entry Point
------------------------------------------
This file just starts the bot and loads every cog (command file)
inside the cogs/ folder automatically. To add a new command later,
just drop a new .py file in cogs/ - you don't need to edit this file.
"""

import os
import json
import time
import asyncio
import traceback
import discord
import aiohttp
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from permissions import is_command_allowed, load_config, is_command_enabled, load_toggles, is_maintenance_blocking, load_maintenance

load_dotenv()

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")

# Defaults to your real server. Add GUILD_ID=your_test_server_id to a
# local .env (never commit it) to point a dev/test bot at a different
# server without touching this file.
GUILD_ID = int(os.environ.get("GUILD_ID", 1535372103593894028))

# Optional - add LOG_WEBHOOK_URL=... to your .env to get bot startup/error
# notifications posted to a private log channel. Leave unset to disable.
LOG_WEBHOOK_URL = os.environ.get("LOG_WEBHOOK_URL")

LOCAL_LOG_FILE = os.path.join(os.path.dirname(__file__), "bot_logs.json")
MAX_LOCAL_LOGS = 300


def record_local_log(level: str, message: str):
    """Best-effort local log, capped at MAX_LOCAL_LOGS entries - read by the
    dashboard's Logs tab. Separate from the optional Discord webhook."""
    try:
        logs = []
        if os.path.exists(LOCAL_LOG_FILE):
            with open(LOCAL_LOG_FILE, "r", encoding="utf-8") as f:
                logs = json.load(f)
        logs.append({"time": int(time.time()), "level": level, "message": message})
        logs = logs[-MAX_LOCAL_LOGS:]
        with open(LOCAL_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(logs, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️ Failed to write local log: {e}")


async def send_log(content: str, level: str = "info"):
    """Posts a message to the log webhook (if configured) AND records it
    locally for the dashboard's Logs tab."""
    record_local_log(level, content)
    if not LOG_WEBHOOK_URL:
        return
    try:
        async with aiohttp.ClientSession() as session:
            webhook = discord.Webhook.from_url(LOG_WEBHOOK_URL, session=session)
            await webhook.send(content[:2000], username="Bot Logs")
    except Exception as e:
        print(f"⚠️ Failed to send log webhook: {e}")


class PermissionedTree(app_commands.CommandTree):
    """Runs before every single slash command (including subcommands) -
    see permissions.py to control who can use what."""

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if is_command_allowed(interaction):
            return True

        command_name = interaction.command.qualified_name if interaction.command else None

        if isinstance(interaction.user, discord.Member) and is_maintenance_blocking(interaction.user.id):
            await interaction.response.send_message(
                "🔧 The bot is currently under maintenance. Try again shortly.", ephemeral=True
            )
        elif command_name and not is_command_enabled(command_name):
            await interaction.response.send_message(
                "🚫 This command is currently disabled.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "🚫 You don't have permission to use this command.", ephemeral=True
            )
        return False

    async def on_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        # Permission denials are already handled above and are expected, not real errors
        if isinstance(error, app_commands.CheckFailure):
            return

        command_name = interaction.command.qualified_name if interaction.command else "unknown"
        tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        print(f"⚠️ Error in /{command_name}:\n{tb}")
        await send_log(f"⚠️ **Error in `/{command_name}`** (used by {interaction.user})\n```{tb[-1800:]}```", level="error")


intents = discord.Intents.default()
intents.members = True  # required so {@name} placeholders can find users, not just roles
bot = commands.Bot(command_prefix="!", intents=intents, tree_cls=PermissionedTree)


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    await send_log(f"✅ **{bot.user}** is now online.")

    load_config()  # creates permissions_config.json now if it doesn't exist yet
    load_toggles()  # creates command_toggles.json now if it doesn't exist yet
    load_maintenance()  # creates maintenance.json now if it doesn't exist yet
    print("✅ permissions_config.json ready")

    try:
        guild = discord.Object(id=GUILD_ID)

        # Register commands to your server first (while they're still in memory)
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        print(f"✅ Synced {len(synced)} slash command(s) to your server (instant)")

        # Now clear any old GLOBAL commands from previous syncs (removes duplicates)
        bot.tree.clear_commands(guild=None)
        await bot.tree.sync()
    except Exception as e:
        print(f"⚠️ Failed to sync commands: {e}")


async def load_cogs():
    cogs_dir = os.path.join(os.path.dirname(__file__), "cogs")
    for filename in os.listdir(cogs_dir):
        if filename.endswith(".py") and not filename.startswith("_"):
            cog_name = f"cogs.{filename[:-3]}"
            try:
                await bot.load_extension(cog_name)
                print(f"✅ Loaded cog: {cog_name}")
            except Exception as e:
                print(f"⚠️ Failed to load {cog_name}: {e}")


async def main():
    async with bot:
        await load_cogs()
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("❌ DISCORD_TOKEN not found. Check your .env file.")
    else:
        asyncio.run(main())