"""
Server Config (welcome/leave messages, auto-role)
------------------------------------------
Reads a per-server config (edited via the web dashboard's Server Config
tab, or by hand) and acts on member join/leave events accordingly. No
slash commands here on purpose - this is dashboard-managed.

Per-server: stored under guild_data/<guild_id>/server_config.json, so
each community's welcome message, auto-role, etc. are independent.

Fields (all optional):
{
  "welcome_channel_id": "123...",
  "welcome_message": "Welcome {mention} to {server}!",
  "leave_channel_id": "123...",
  "leave_message": "{user} has left {server}.",
  "auto_role_id": "123...",
  "log_channel_id": "123..."
}

Placeholders in welcome/leave messages: {mention} {user} {server}
"""

import os
import json
import discord
from discord.ext import commands

from guild_paths import guild_file

DEFAULT_CONFIG = {
    "welcome_channel_id": None,
    "welcome_message": "Welcome {mention} to {server}!",
    "leave_channel_id": None,
    "leave_message": "{user} has left {server}.",
    "auto_role_id": None,
    "log_channel_id": None,
}


def load_config(guild_id: int) -> dict:
    path = guild_file(guild_id, "server_config.json")
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
        return dict(DEFAULT_CONFIG)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    merged = dict(DEFAULT_CONFIG)
    merged.update(data)
    return merged


def fill_placeholders(template: str, member: discord.Member) -> str:
    return (
        template.replace("{mention}", member.mention)
        .replace("{user}", member.display_name)
        .replace("{server}", member.guild.name)
    )


class ServerConfig(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        config = load_config(member.guild.id)

        if config.get("auto_role_id"):
            role = member.guild.get_role(int(config["auto_role_id"]))
            if role:
                try:
                    await member.add_roles(role, reason="Auto-role on join")
                except discord.Forbidden:
                    pass

        if config.get("welcome_channel_id"):
            channel = member.guild.get_channel(int(config["welcome_channel_id"]))
            if channel:
                try:
                    await channel.send(fill_placeholders(config["welcome_message"], member))
                except discord.Forbidden:
                    pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        config = load_config(member.guild.id)

        if config.get("leave_channel_id"):
            channel = member.guild.get_channel(int(config["leave_channel_id"]))
            if channel:
                try:
                    await channel.send(fill_placeholders(config["leave_message"], member))
                except discord.Forbidden:
                    pass


async def setup(bot: commands.Bot):
    await bot.add_cog(ServerConfig(bot))
