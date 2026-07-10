"""
/blocker command group
------------------------
Track things currently blocking progress (e.g. "waiting on new UI assets")
so they're visible to the whole team instead of buried in chat. Posts as a
"live" message that auto-updates - same pattern as /roadmap and /team.

Subcommands:
  /blocker add     - log a new blocker
  /blocker resolve - mark a blocker as resolved (removes it from the active list)
  /blocker show    - post (or move) the live blocker list to this channel
  /blocker clear   - wipe all blockers
"""

import os
import json
import discord
from discord import app_commands
from discord.ext import commands

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "blocker_data.json")

SEVERITY_CHOICES = [
    app_commands.Choice(name="🟡 Low", value="low"),
    app_commands.Choice(name="🟠 Medium", value="medium"),
    app_commands.Choice(name="🔴 High", value="high"),
    app_commands.Choice(name="⛔ Critical", value="critical"),
]

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
SEVERITY_LABELS = {"low": "🟡 Low", "medium": "🟠 Medium", "high": "🔴 High", "critical": "⛔ Critical"}


def load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        return {"blockers": [], "channel_id": None, "message_id": None}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("blockers", [])
    data.setdefault("channel_id", None)
    data.setdefault("message_id", None)
    return data


def save_data(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def build_blocker_embed(data: dict) -> discord.Embed:
    embed = discord.Embed(title="🚧 Active Blockers", color=discord.Color.red())

    blockers = sorted(data["blockers"], key=lambda b: SEVERITY_ORDER.get(b["severity"], 99))

    if not blockers:
        embed.description = "*Nothing blocking progress right now. 🎉*"
    else:
        lines = []
        for i, b in enumerate(blockers):
            line = f"`{i+1}.` {SEVERITY_LABELS[b['severity']]} — {b['description']}"
            if b.get("reported_by"):
                line += f"\n     _reported by {b['reported_by']}_"
            lines.append(line)
        embed.description = "\n".join(lines)

    embed.set_footer(text="Updates automatically when blockers are added or resolved.")
    return embed


class Blocker(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    blocker_group = app_commands.Group(name="blocker", description="Track things currently blocking progress")

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

        await message.edit(embed=build_blocker_embed(data))
        return True

    @blocker_group.command(name="add", description="Log a new blocker")
    @app_commands.describe(
        description="What's blocking progress, e.g. 'Waiting on new UI assets'",
        severity="How serious is this blocker?",
    )
    @app_commands.choices(severity=SEVERITY_CHOICES)
    async def add(self, interaction: discord.Interaction, description: str, severity: app_commands.Choice[str]):
        data = load_data()
        data["blockers"].append({
            "description": description,
            "severity": severity.value,
            "reported_by": interaction.user.display_name,
        })
        save_data(data)
        updated_live = await self.refresh_live_message(data)
        note = "" if updated_live else "\n*(No live blocker message set yet - use `/blocker show` in a channel first.)*"
        await interaction.response.send_message(
            f"✅ Logged blocker ({SEVERITY_LABELS[severity.value]}): {description}{note}", ephemeral=True
        )

    @blocker_group.command(name="resolve", description="Mark a blocker as resolved and remove it")
    @app_commands.describe(number="Blocker number (see /blocker show)")
    async def resolve(self, interaction: discord.Interaction, number: int):
        data = load_data()
        blockers = sorted(data["blockers"], key=lambda b: SEVERITY_ORDER.get(b["severity"], 99))

        if number < 1 or number > len(blockers):
            await interaction.response.send_message(
                f"⚠️ There's no blocker #{number}. Use `/blocker show` to see current numbers.", ephemeral=True
            )
            return

        target = blockers[number - 1]
        data["blockers"].remove(target)
        save_data(data)
        updated_live = await self.refresh_live_message(data)
        note = "" if updated_live else "\n*(No live blocker message set yet - use `/blocker show` in a channel first.)*"
        await interaction.response.send_message(f"✅ Resolved: {target['description']}{note}", ephemeral=True)

    @blocker_group.command(name="clear", description="Clear all blockers")
    async def clear(self, interaction: discord.Interaction):
        data = load_data()
        data["blockers"] = []
        save_data(data)
        updated_live = await self.refresh_live_message(data)
        note = "" if updated_live else "\n*(No live blocker message set yet - use `/blocker show` in a channel first.)*"
        await interaction.response.send_message(f"🧹 All blockers cleared.{note}", ephemeral=True)

    @blocker_group.command(name="show", description="Post (or move) the live blocker list to this channel")
    async def show(self, interaction: discord.Interaction):
        data = load_data()
        embed = build_blocker_embed(data)
        await interaction.response.send_message(embed=embed)
        sent_message = await interaction.original_response()

        data["channel_id"] = interaction.channel_id
        data["message_id"] = sent_message.id
        save_data(data)


async def setup(bot: commands.Bot):
    await bot.add_cog(Blocker(bot))