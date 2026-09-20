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

# Optional legacy/primary server. Approved servers are discovered from the
# guild registry and synced below, so this is no longer the only server.
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
        normalized_level = level.lower()
        lowered_content = content.lower()

        if normalized_level == "error" or "error" in lowered_content:
            title = "🚨 Application Error"
            color = discord.Color.red()
        elif "rejoined approved server" in lowered_content:
            title = "🔄 Server Rejoined"
            color = discord.Color.green()
        elif "tried to add the bot" in lowered_content:
            title = "📥 Server Join Request"
            color = discord.Color.orange()
        elif "is now online" in lowered_content:
            title = "✅ Bot Online"
            color = discord.Color.green()
        else:
            title = "📋 Bot Activity"
            color = discord.Color.blurple()

        embed = discord.Embed(
            title=title,
            description=content[:4000],
            color=color,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Event", value=title.split(" ", 1)[1], inline=True)
        embed.add_field(name="Severity", value=normalized_level.upper(), inline=True)
        embed.set_footer(text="Star Wars Server Bot • Log webhook")

        async with aiohttp.ClientSession() as session:
            webhook = discord.Webhook.from_url(LOG_WEBHOOK_URL, session=session)
            await webhook.send(embed=embed, username="Bot Logs")
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


async def sync_approved_guild_commands():
    """Register the loaded slash commands in every approved server.

    Guild-scoped registration makes commands available immediately and avoids
    relying on Discord's much slower global-command propagation.
    """
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from economy.services import registry_service as reg

    guild_ids = {GUILD_ID}
    guild_ids.update(entry.guild_id for entry in reg.list_all() if entry.status == "approved" and entry.bot_enabled)

    total = 0
    synced_guilds = 0
    for guild_id in guild_ids:
        if bot.get_guild(guild_id) is None:
            print(f"⚠️ Skipping command sync for guild {guild_id}: bot is not a member")
            continue
        guild = discord.Object(id=guild_id)
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        total += len(synced)
        synced_guilds += 1
        print(f"✅ Synced {len(synced)} slash command(s) to guild {guild_id}")

    # Remove any global commands left by an older one-server deployment.
    bot.tree.clear_commands(guild=None)
    await bot.tree.sync()

    return synced_guilds, total


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    await send_log(f"✅ **{bot.user}** is now online.")

    load_config()  # creates permissions_config.json now if it doesn't exist yet
    load_toggles()  # creates command_toggles.json now if it doesn't exist yet
    load_maintenance()  # creates maintenance.json now if it doesn't exist yet
    print("✅ permissions_config.json ready")

    try:
        guild_count, command_count = await sync_approved_guild_commands()
        print(f"✅ Synced {command_count} command registration(s) across {guild_count} server(s)")
    except Exception as e:
        print(f"⚠️ Failed to sync commands: {e}")


@bot.event
async def on_guild_join(guild: discord.Guild):
    """
    New servers must be approved before the bot stays. Approved servers get
    their guild-scoped slash commands synced immediately after rejoining.
    """
    if guild.id == GUILD_ID:
        return  # preserve the legacy/primary server behavior

    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from economy.services import registry_service as reg

    existing = reg.get_request_for_guild(guild.id)
    if existing and existing.status == "approved" and existing.bot_enabled:
        bot.tree.copy_global_to(guild=discord.Object(id=guild.id))
        synced = await bot.tree.sync(guild=discord.Object(id=guild.id))
        await send_log(f"✅ Rejoined approved server: **{guild.name}**.")
        print(f"✅ Synced {len(synced)} slash command(s) to rejoined guild {guild.id}")
        return

    owner = guild.owner or (await guild.fetch_member(guild.owner_id) if guild.owner_id else None)
    owner_name = str(owner) if owner else "Unknown"
    owner_id = guild.owner_id or 0

    entry = reg.auto_register_pending(guild.id, guild.name, owner_id, owner_name)

    dashboard_url = os.environ.get("DASHBOARD_PUBLIC_URL", "the dashboard")
    dm_text = (
        f"👋 Thanks for adding **{bot.user.name}** to **{guild.name}**!\n\n"
        f"This bot requires approval before it can be used here. "
        f"Your request has been submitted automatically"
        + (f" - you can check its status or add a note at {dashboard_url}" if dashboard_url != "the dashboard" else "")
        + f".\n\nThe bot will leave this server for now and rejoin automatically once approved."
    )

    if owner:
        try:
            await owner.send(dm_text)
        except discord.Forbidden:
            pass  # owner has DMs disabled - the pending request still exists for them to find via the dashboard

    await send_log(f"📥 New server tried to add the bot: **{guild.name}** (owner: {owner_name}) - registered as pending and left.")

    await guild.leave()


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

    economy_cogs_dir = os.path.join(os.path.dirname(__file__), "economy", "cogs")
    if os.path.isdir(economy_cogs_dir):
        for filename in os.listdir(economy_cogs_dir):
            if filename.endswith(".py") and not filename.startswith("_"):
                cog_name = f"economy.cogs.{filename[:-3]}"
                try:
                    await bot.load_extension(cog_name)
                    print(f"✅ Loaded cog: {cog_name}")
                except Exception as e:
                    print(f"⚠️ Failed to load {cog_name}: {e}")


async def main():
    async with bot:
        from economy.db import init_db
        init_db()
        print("✅ Economy database ready")

        await load_cogs()
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("❌ DISCORD_TOKEN not found. Check your .env file.")
    else:
        asyncio.run(main())