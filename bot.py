"""
Star Wars Server Bot - Main Entry Point
------------------------------------------
This file just starts the bot and loads every cog (command file)
inside the cogs/ folder automatically. To add a new command later,
just drop a new .py file in cogs/ - you don't need to edit this file.
"""

import os
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from permissions import is_command_allowed, load_config

load_dotenv()

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")

# Defaults to your real server. Add GUILD_ID=your_test_server_id to a
# local .env (never commit it) to point a dev/test bot at a different
# server without touching this file.
GUILD_ID = int(os.environ.get("GUILD_ID", 1535372103593894028))


class PermissionedTree(app_commands.CommandTree):
    """Runs before every single slash command (including subcommands) -
    see permissions.py to control who can use what."""

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if is_command_allowed(interaction):
            return True
        await interaction.response.send_message(
            "🚫 You don't have permission to use this command.", ephemeral=True
        )
        return False


intents = discord.Intents.default()
intents.members = True  # required so {@name} placeholders can find users, not just roles
bot = commands.Bot(command_prefix="!", intents=intents, tree_cls=PermissionedTree)


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")

    load_config()  # creates permissions_config.json now if it doesn't exist yet
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