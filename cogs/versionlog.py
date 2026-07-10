"""
/versionlog command group
------------------------
Track what version is currently live vs in testing, with a running history.
Posts as a "live" message that auto-updates - same pattern as the others.

Subcommands:
  /versionlog set     - set the current live or testing version
  /versionlog show    - post (or move) the live status card to this channel
  /versionlog history - see the full change history
  /versionlog clear   - wipe everything
"""

import os
import json
from datetime import date
import discord
from discord import app_commands
from discord.ext import commands

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "versionlog_data.json")

CHANNEL_CHOICES = [
    app_commands.Choice(name="🟢 Live", value="live"),
    app_commands.Choice(name="🔵 Testing", value="testing"),
]


def load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        return {"live_version": None, "testing_version": None, "history": [], "channel_id": None, "message_id": None}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("live_version", None)
    data.setdefault("testing_version", None)
    data.setdefault("history", [])
    data.setdefault("channel_id", None)
    data.setdefault("message_id", None)
    return data


def save_data(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def build_versionlog_embed(data: dict) -> discord.Embed:
    embed = discord.Embed(title="🛰️ Version Status", color=discord.Color.dark_teal())

    embed.add_field(name="🟢 Live", value=data["live_version"] or "*Not set*", inline=True)
    embed.add_field(name="🔵 Testing", value=data["testing_version"] or "*Not set*", inline=True)

    recent = data["history"][-5:][::-1]
    if recent:
        lines = [f"`{h['date']}` {h['channel']}: **{h['version']}**" + (f" — {h['notes']}" if h.get("notes") else "") for h in recent]
        embed.add_field(name="Recent history", value="\n".join(lines), inline=False)

    embed.set_footer(text="Updates automatically when a version is set.")
    return embed


class Versionlog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    versionlog_group = app_commands.Group(name="versionlog", description="Track live vs testing version status")

    async def refresh_live_message(self, data: dict):
        channel_id = data.get("channel_id")
        message_id = data.get("message_id")
        if not channel_id or not message_id:
            return False

        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except discord.HTTPException:
                return False

        try:
            message = await channel.fetch_message(message_id)
        except discord.HTTPException:
            return False

        await message.edit(embed=build_versionlog_embed(data))
        return True

    @versionlog_group.command(name="set", description="Set the current live or testing version")
    @app_commands.describe(channel="Which one to update", version="Version/build name, e.g. 'v1.4.2'", notes="Optional short note")
    @app_commands.choices(channel=CHANNEL_CHOICES)
    async def set_version(
        self,
        interaction: discord.Interaction,
        channel: app_commands.Choice[str],
        version: str,
        notes: str = "",
    ):
        data = load_data()
        if channel.value == "live":
            data["live_version"] = version
        else:
            data["testing_version"] = version

        data["history"].append({
            "channel": "🟢 Live" if channel.value == "live" else "🔵 Testing",
            "version": version,
            "notes": notes,
            "date": date.today().isoformat(),
        })
        save_data(data)

        updated_live = await self.refresh_live_message(data)
        note = "" if updated_live else "\n*(No live status message set yet - use `/versionlog show` in a channel first.)*"
        await interaction.response.send_message(
            f"✅ Set **{channel.name}** version to **{version}**.{note}", ephemeral=True
        )

    @versionlog_group.command(name="history", description="See the full version change history")
    async def history(self, interaction: discord.Interaction):
        data = load_data()
        if not data["history"]:
            await interaction.response.send_message("No version history logged yet.", ephemeral=True)
            return

        lines = [
            f"`{h['date']}` {h['channel']}: **{h['version']}**" + (f" — {h['notes']}" if h.get("notes") else "")
            for h in reversed(data["history"])
        ]
        embed = discord.Embed(title="📜 Version History", description="\n".join(lines[:25]), color=discord.Color.dark_teal())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @versionlog_group.command(name="clear", description="Wipe all version data and history")
    async def clear(self, interaction: discord.Interaction):
        data = load_data()
        data["live_version"] = None
        data["testing_version"] = None
        data["history"] = []
        save_data(data)
        updated_live = await self.refresh_live_message(data)
        note = "" if updated_live else "\n*(No live status message set yet - use `/versionlog show` in a channel first.)*"
        await interaction.response.send_message(f"🧹 Version log cleared.{note}", ephemeral=True)

    @versionlog_group.command(name="show", description="Post (or move) the live version status to this channel")
    async def show(self, interaction: discord.Interaction):
        data = load_data()
        embed = build_versionlog_embed(data)
        await interaction.response.send_message(embed=embed)
        sent_message = await interaction.original_response()

        data["channel_id"] = interaction.channel_id
        data["message_id"] = sent_message.id
        save_data(data)


async def setup(bot: commands.Bot):
    await bot.add_cog(Versionlog(bot))