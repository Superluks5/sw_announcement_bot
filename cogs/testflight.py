"""
/testflight command group
------------------------
Track who's testing a build/update and their status. Posts as a "live"
message that auto-updates - same pattern as /roadmap, /team, /blocker.

Subcommands:
  /testflight add     - add a tester to a build (starts as "Not started")
  /testflight update  - update a tester's status + optional feedback
  /testflight remove  - remove a tester entry
  /testflight show    - post (or move) the live tester list to this channel
  /testflight clear   - wipe all entries (optionally just for one build)
"""

import os
import json
import discord
from discord import app_commands
from discord.ext import commands

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "testflight_data.json")

STATUS_CHOICES = [
    app_commands.Choice(name="⚪ Not started", value="not_started"),
    app_commands.Choice(name="🔵 Testing", value="testing"),
    app_commands.Choice(name="✅ Done", value="done"),
]
STATUS_LABELS = {"not_started": "⚪ Not started", "testing": "🔵 Testing", "done": "✅ Done"}
STATUS_ORDER = {"testing": 0, "not_started": 1, "done": 2}


def load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        return {"entries": [], "channel_id": None, "message_id": None}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("entries", [])
    data.setdefault("channel_id", None)
    data.setdefault("message_id", None)
    return data


def save_data(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def find_entry(data: dict, tester_id: int, build: str):
    return next(
        (e for e in data["entries"] if e["tester_id"] == tester_id and e["build"].lower() == build.lower()),
        None,
    )


def build_testflight_embed(data: dict) -> discord.Embed:
    embed = discord.Embed(title="🧪 Testflight Status", color=discord.Color.teal())

    if not data["entries"]:
        embed.description = "*No testers logged yet.*"
        embed.set_footer(text="Updates automatically when testers are added or updated.")
        return embed

    by_build = {}
    for e in data["entries"]:
        by_build.setdefault(e["build"], []).append(e)

    for build, entries in by_build.items():
        entries_sorted = sorted(entries, key=lambda e: STATUS_ORDER.get(e["status"], 99))
        lines = []
        for e in entries_sorted:
            line = f"<@{e['tester_id']}> — {STATUS_LABELS[e['status']]}"
            if e.get("feedback"):
                line += f"\n     _{e['feedback']}_"
            lines.append(line)
        embed.add_field(name=f"📦 {build}", value="\n".join(lines), inline=False)

    embed.set_footer(text="Updates automatically when testers are added or updated.")
    return embed


class Testflight(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    testflight_group = app_commands.Group(name="testflight", description="Track testers and feedback status per build")

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

        await message.edit(embed=build_testflight_embed(data))
        return True

    @testflight_group.command(name="add", description="Add a tester to a build")
    @app_commands.describe(tester="Who's testing", build="Build name/version, e.g. 'v1.4 Beta'")
    async def add(self, interaction: discord.Interaction, tester: discord.Member, build: str):
        data = load_data()

        if find_entry(data, tester.id, build):
            await interaction.response.send_message(
                f"⚠️ {tester.mention} is already logged for **{build}**. Use `/testflight update` to change their status.",
                ephemeral=True,
            )
            return

        data["entries"].append({
            "tester_id": tester.id,
            "build": build,
            "status": "not_started",
            "feedback": "",
        })
        save_data(data)
        updated_live = await self.refresh_live_message(data)
        note = "" if updated_live else "\n*(No live testflight message set yet - use `/testflight show` in a channel first.)*"
        await interaction.response.send_message(
            f"✅ {tester.mention} added as a tester for **{build}**.{note}", ephemeral=True
        )

    @testflight_group.command(name="update", description="Update a tester's status and/or feedback")
    @app_commands.describe(
        tester="Which tester",
        build="Which build",
        status="New status",
        feedback="Optional feedback note",
    )
    @app_commands.choices(status=STATUS_CHOICES)
    async def update(
        self,
        interaction: discord.Interaction,
        tester: discord.Member,
        build: str,
        status: app_commands.Choice[str],
        feedback: str = "",
    ):
        data = load_data()
        entry = find_entry(data, tester.id, build)

        if not entry:
            await interaction.response.send_message(
                f"⚠️ {tester.mention} isn't logged for **{build}** yet. Use `/testflight add` first.",
                ephemeral=True,
            )
            return

        entry["status"] = status.value
        if feedback:
            entry["feedback"] = feedback

        save_data(data)
        updated_live = await self.refresh_live_message(data)
        note = "" if updated_live else "\n*(No live testflight message set yet - use `/testflight show` in a channel first.)*"
        await interaction.response.send_message(
            f"✅ Updated {tester.mention} on **{build}** → {STATUS_LABELS[status.value]}{note}", ephemeral=True
        )

    @testflight_group.command(name="remove", description="Remove a tester entry")
    @app_commands.describe(tester="Which tester", build="Which build")
    async def remove(self, interaction: discord.Interaction, tester: discord.Member, build: str):
        data = load_data()
        entry = find_entry(data, tester.id, build)

        if not entry:
            await interaction.response.send_message(
                f"⚠️ {tester.mention} isn't logged for **{build}**.", ephemeral=True
            )
            return

        data["entries"].remove(entry)
        save_data(data)
        updated_live = await self.refresh_live_message(data)
        note = "" if updated_live else "\n*(No live testflight message set yet - use `/testflight show` in a channel first.)*"
        await interaction.response.send_message(
            f"🗑️ Removed {tester.mention} from **{build}**.{note}", ephemeral=True
        )

    @testflight_group.command(name="clear", description="Clear all testflight entries (optionally just one build)")
    @app_commands.describe(build="Optional - only clear this build. Leave blank to clear everything.")
    async def clear(self, interaction: discord.Interaction, build: str = None):
        data = load_data()
        if build:
            data["entries"] = [e for e in data["entries"] if e["build"].lower() != build.lower()]
            label = build
        else:
            data["entries"] = []
            label = "all builds"

        save_data(data)
        updated_live = await self.refresh_live_message(data)
        note = "" if updated_live else "\n*(No live testflight message set yet - use `/testflight show` in a channel first.)*"
        await interaction.response.send_message(f"🧹 Cleared entries for **{label}**.{note}", ephemeral=True)

    @testflight_group.command(name="show", description="Post (or move) the live testflight status to this channel")
    async def show(self, interaction: discord.Interaction):
        data = load_data()
        embed = build_testflight_embed(data)
        await interaction.response.send_message(embed=embed)
        sent_message = await interaction.original_response()

        data["channel_id"] = interaction.channel_id
        data["message_id"] = sent_message.id
        save_data(data)


async def setup(bot: commands.Bot):
    await bot.add_cog(Testflight(bot))