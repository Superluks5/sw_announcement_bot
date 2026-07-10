"""
/team command group
------------------------
Maintains a staff/dev team roster and posts it as a "live" message that
auto-updates whenever someone is added or removed - same pattern as /roadmap.

Subcommands:
  /team add    - add a member with their role/title
  /team remove - remove a member from the roster
  /team show   - post (or move) the live roster message to this channel
  /team clear  - wipe the whole roster
"""

import os
import json
import discord
from discord import app_commands
from discord.ext import commands

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "team_data.json")


def load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        return {"members": [], "channel_id": None, "message_id": None}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("members", [])
    data.setdefault("channel_id", None)
    data.setdefault("message_id", None)
    return data


def save_data(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def build_team_embed(data: dict) -> discord.Embed:
    embed = discord.Embed(title="👥 Team Roster", color=discord.Color.blue())

    if not data["members"]:
        embed.description = "*No team members listed yet.*"
    else:
        lines = [f"`{i+1}.` <@{m['user_id']}> — **{m['role']}**" for i, m in enumerate(data["members"])]
        embed.description = "\n".join(lines)

    embed.set_footer(text="Updates automatically when members are added or removed.")
    return embed


class TeamList(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    team_group = app_commands.Group(name="team", description="Manage and post the team roster")

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

        await message.edit(embed=build_team_embed(data))
        return True

    @team_group.command(name="add", description="Add a member to the team roster")
    @app_commands.describe(member="Who to add", role="Their role/title, e.g. 'Lead Developer'")
    async def add(self, interaction: discord.Interaction, member: discord.Member, role: str):
        data = load_data()

        # Update role if already listed, otherwise add new
        existing = next((m for m in data["members"] if m["user_id"] == member.id), None)
        if existing:
            existing["role"] = role
        else:
            data["members"].append({"user_id": member.id, "role": role})

        save_data(data)
        updated_live = await self.refresh_live_message(data)
        note = "" if updated_live else "\n*(No live roster message set yet - use `/team show` in a channel first.)*"
        await interaction.response.send_message(
            f"✅ {member.mention} added as **{role}**.{note}", ephemeral=True
        )

    @team_group.command(name="remove", description="Remove a member from the team roster")
    @app_commands.describe(member="Who to remove")
    async def remove(self, interaction: discord.Interaction, member: discord.Member):
        data = load_data()
        before = len(data["members"])
        data["members"] = [m for m in data["members"] if m["user_id"] != member.id]

        if len(data["members"]) == before:
            await interaction.response.send_message(f"⚠️ {member.mention} isn't on the roster.", ephemeral=True)
            return

        save_data(data)
        updated_live = await self.refresh_live_message(data)
        note = "" if updated_live else "\n*(No live roster message set yet - use `/team show` in a channel first.)*"
        await interaction.response.send_message(f"🗑️ {member.mention} removed from the roster.{note}", ephemeral=True)

    @team_group.command(name="clear", description="Clear the entire team roster")
    async def clear(self, interaction: discord.Interaction):
        data = load_data()
        data["members"] = []
        save_data(data)
        updated_live = await self.refresh_live_message(data)
        note = "" if updated_live else "\n*(No live roster message set yet - use `/team show` in a channel first.)*"
        await interaction.response.send_message(f"🧹 Roster cleared.{note}", ephemeral=True)

    @team_group.command(name="show", description="Post (or move) the live team roster to this channel")
    async def show(self, interaction: discord.Interaction):
        data = load_data()
        embed = build_team_embed(data)
        await interaction.response.send_message(embed=embed)
        sent_message = await interaction.original_response()

        data["channel_id"] = interaction.channel_id
        data["message_id"] = sent_message.id
        save_data(data)


async def setup(bot: commands.Bot):
    await bot.add_cog(TeamList(bot))
