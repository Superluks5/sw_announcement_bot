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
from datetime import datetime, timezone
import discord
import aiohttp
from discord import app_commands
from discord.ext import commands, tasks
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
REVIEW_INVITE_MAX_AGE = int(os.environ.get("REVIEW_INVITE_MAX_AGE", "86400"))

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

        if interaction.guild_id and isinstance(interaction.user, discord.Member) and is_maintenance_blocking(interaction.guild_id, interaction.user.id):
            await interaction.response.send_message(
                "🔧 The bot is currently under maintenance. Try again shortly.", ephemeral=True
            )
        elif command_name and interaction.guild_id and not is_command_enabled(interaction.guild_id, command_name):
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
bot.send_log = send_log


@tasks.loop(minutes=10)
async def sync_registry_periodically():
    try:
        await sync_discovered_guilds()
    except Exception as error:
        print(f"⚠️ Periodic server discovery failed: {error}")
        await send_log(f"❌ Periodic server discovery failed: `{error}`", level="error")


@sync_registry_periodically.before_loop
async def before_sync_registry_periodically():
    await bot.wait_until_ready()


@sync_registry_periodically.error
async def sync_registry_periodically_error(error: Exception):
    await send_log(f"❌ Server discovery task stopped: `{error}`", level="error")


@bot.event
async def on_disconnect():
    await send_log("🔌 Discord connection lost. The bot is attempting to reconnect.", level="warning")


@bot.event
async def on_resumed():
    await send_log("🔁 Discord connection resumed successfully.")


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


async def create_guild_invite(guild: discord.Guild) -> tuple[str | None, str | None]:
    """Create a reusable invite and return a useful failure reason."""
    me = guild.me
    if me is None:
        return None, "Bot member is not available in the guild cache"
    checked_channels = 0
    for channel in guild.text_channels:
        checked_channels += 1
        permissions = channel.permissions_for(me)
        if not permissions.create_instant_invite:
            continue
        try:
            invite = await channel.create_invite(
                max_age=REVIEW_INVITE_MAX_AGE,
                max_uses=0,
                unique=True,
                reason="Owner Panel review invite",
            )
            return invite.url, None
        except discord.HTTPException as error:
            return None, str(error)
    if checked_channels == 0:
        return None, "No text channels available"
    return None, "Bot lacks Create Invite permission in every text channel"


def guild_snapshot(guild: discord.Guild) -> tuple[int, int, int, str, str]:
    me = guild.me
    permission_summary = "member unavailable"
    if me is not None:
        permissions = [
            name for name, allowed in {
                "administrator": me.guild_permissions.administrator,
                "create_invite": me.guild_permissions.create_instant_invite,
                "view_channels": me.guild_permissions.view_channel,
                "send_messages": me.guild_permissions.send_messages,
            }.items() if allowed
        ]
        permission_summary = ", ".join(permissions) or "no key permissions"
    snapshot = json.dumps({
        "name": guild.name,
        "owner_id": guild.owner_id,
        "member_count": guild.member_count,
        "channel_count": len(guild.channels),
        "role_count": len(guild.roles),
        "permissions": permission_summary,
    }, ensure_ascii=True)
    return (
        guild.member_count or 0,
        len(guild.channels),
        len(guild.roles),
        permission_summary,
        snapshot,
    )


async def sync_discovered_guilds():
    """Ensure servers already containing the bot appear in the Owner Panel."""
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from economy.services import registry_service as reg

    current_ids = {guild.id for guild in bot.guilds}
    for entry in reg.list_all():
        if entry.guild_id not in current_ids and entry.bot_present:
            reg.update_presence(entry.id, False)

    discovered = 0
    for guild in bot.guilds:
        entry = reg.get_request_for_guild(guild.id)
        if entry is None:
            owner = guild.owner
            if owner is None and guild.owner_id:
                try:
                    owner = await guild.fetch_member(guild.owner_id)
                except discord.HTTPException:
                    owner = None
            entry = reg.auto_register_pending(
                guild.id,
                guild.name,
                guild.owner_id or 0,
                str(owner) if owner else "Unknown",
            )
            discovered += 1
        member_count, channel_count, role_count, permissions, snapshot = guild_snapshot(guild)
        invite_url = entry.invite_url
        invite_expired = False
        if entry.invite_expires_at:
            expiry = entry.invite_expires_at
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            invite_expired = expiry <= datetime.now(timezone.utc)
        invite_error = None
        if invite_url is None or invite_expired:
            invite_url, invite_error = await create_guild_invite(guild)
            if invite_url:
                entry = reg.set_invite(entry.id, invite_url, REVIEW_INVITE_MAX_AGE)
            else:
                reg.set_invite_error(entry.id, invite_error or "Unknown invite error")
        reg.update_presence(
            entry.id, True, guild.name, member_count, channel_count, role_count, permissions, snapshot
        )

    if discovered:
        await send_log(f"🔎 Discovered **{discovered}** existing server(s) and added them to the Owner Panel.")
    return discovered


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    await send_log(f"✅ **{bot.user}** is now online.")

    try:
        import sys
        sys.path.insert(0, os.path.dirname(__file__))
        from economy.services import registry_service as reg

        guild_ids = {GUILD_ID}
        guild_ids.update(entry.guild_id for entry in reg.list_all() if entry.status == "approved")
        for gid in guild_ids:
            load_config(gid)  # creates that guild's permissions_config.json if it doesn't exist yet
            load_toggles(gid)
            load_maintenance(gid)
        print(f"✅ Bot configuration ready for {len(guild_ids)} guild(s)")
        await send_log("⚙️ Bot configuration loaded successfully.")
    except Exception as e:
        print(f"⚠️ Failed to load bot configuration: {e}")
        await send_log(f"❌ Failed to load bot configuration: `{e}`", level="error")
        raise

    try:
        await sync_discovered_guilds()
        guild_count, command_count = await sync_approved_guild_commands()
        print(f"✅ Synced {command_count} command registration(s) across {guild_count} server(s)")
        await send_log(
            f"🔄 Command sync completed: **{command_count}** command(s) across **{guild_count}** approved server(s)."
        )
    except Exception as e:
        print(f"⚠️ Failed to sync commands: {e}")
        await send_log(f"⚠️ Failed to sync commands: `{e}`", level="error")


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
    invite_url, invite_error = await create_guild_invite(guild)
    if invite_url:
        entry = reg.set_invite(entry.id, invite_url, REVIEW_INVITE_MAX_AGE)
    else:
        reg.set_invite_error(entry.id, invite_error or "Unknown invite error")
    member_count, channel_count, role_count, permissions, snapshot = guild_snapshot(guild)
    reg.update_presence(entry.id, True, guild.name, member_count, channel_count, role_count, permissions, snapshot)

    dashboard_url = os.environ.get("DASHBOARD_PUBLIC_URL", "the dashboard")
    dm_text = (
        f"👋 Thanks for adding **{bot.user.name}** to **{guild.name}**!\n\n"
        f"This bot requires approval before it can be used here. "
        f"Your request has been submitted automatically"
        + (f" - you can check its status or add a note at {dashboard_url}" if dashboard_url != "the dashboard" else "")
        + f".\n\nThe bot will leave this server for now and rejoin automatically once approved."
        + (f"\n\nOwner review invite: {invite_url}" if invite_url else "")
    )

    if owner:
        try:
            await owner.send(dm_text)
        except discord.Forbidden:
            await send_log(
                f"⚠️ Could not DM the owner of **{guild.name}** ({owner_name}); direct messages are disabled.",
                level="warning",
            )
        except discord.HTTPException as e:
            await send_log(f"⚠️ Could not DM the owner of **{guild.name}** ({owner_name}): `{e}`", level="warning")

    await send_log(
        f"📥 New server tried to add the bot: **{guild.name}** (owner: {owner_name}) - "
        f"registered as pending and left. Review invite: {invite_url or 'unavailable'}"
    )

    try:
        await guild.leave()
    except discord.HTTPException as e:
        await send_log(f"❌ Failed to leave unapproved server **{guild.name}**: `{e}`", level="error")
        raise


@bot.event
async def on_guild_remove(guild: discord.Guild):
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from economy.services import registry_service as reg
    entry = reg.get_request_for_guild(guild.id)
    if entry:
        reg.update_presence(entry.id, False)
    await send_log(f"👋 Bot was removed from **{guild.name}** (ID: `{guild.id}`).", level="warning")


async def load_cogs():
    loaded_count = 0

    cogs_dir = os.path.join(os.path.dirname(__file__), "cogs")
    for filename in os.listdir(cogs_dir):
        if filename.endswith(".py") and not filename.startswith("_"):
            cog_name = f"cogs.{filename[:-3]}"
            try:
                await bot.load_extension(cog_name)
                loaded_count += 1
                print(f"✅ Loaded cog: {cog_name}")
            except Exception as e:
                print(f"⚠️ Failed to load {cog_name}: {e}")
                await send_log(f"❌ Failed to load cog `{cog_name}`: `{e}`", level="error")

    economy_cogs_dir = os.path.join(os.path.dirname(__file__), "economy", "cogs")
    if os.path.isdir(economy_cogs_dir):
        for filename in os.listdir(economy_cogs_dir):
            if filename.endswith(".py") and not filename.startswith("_"):
                cog_name = f"economy.cogs.{filename[:-3]}"
                try:
                    await bot.load_extension(cog_name)
                    loaded_count += 1
                    print(f"✅ Loaded cog: {cog_name}")
                except Exception as e:
                    print(f"⚠️ Failed to load {cog_name}: {e}")
                    await send_log(f"❌ Failed to load cog `{cog_name}`: `{e}`", level="error")

    await send_log(f"🧩 Loaded **{loaded_count}** cog(s) successfully.")
    return loaded_count


async def main():
    async with bot:
        from economy.db import init_db
        try:
            init_db()
        except Exception as e:
            await send_log(f"❌ Economy database initialization failed: `{e}`", level="error")
            raise
        print("✅ Economy database ready")
        await send_log("🗄️ Economy database initialized successfully.")

        await load_cogs()
        sync_registry_periodically.start()
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("❌ DISCORD_TOKEN not found. Check your .env file.")
        asyncio.run(send_log("❌ DISCORD_TOKEN is missing. Bot startup aborted.", level="error"))
    else:
        asyncio.run(main())