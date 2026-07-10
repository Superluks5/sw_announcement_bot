"""
/archive command group
------------------------
Snapshots a channel's pinned messages into a tidy summary embed (with
jump links back to the originals), posts that summary to an archive
channel, then unpins everything so the pins list stays clean. Also
keeps a lightweight log of past archive runs.

Subcommands:
  /archive pins        - archive + unpin everything currently pinned here
  /archive setchannel  - set where archive summaries get posted by default
  /archive history     - see past archive runs
"""

import os
import json
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "archive_data.json")


def load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        return {"archive_channel_id": None, "runs": []}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("archive_channel_id", None)
    data.setdefault("runs", [])
    return data


def save_data(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def trim(text: str, length: int = 150) -> str:
    text = text.strip().replace("\n", " ")
    return text if len(text) <= length else text[: length - 1] + "…"


def build_archive_embeds(source_channel: discord.TextChannel, pins: list) -> list:
    """Split pinned messages across embeds so no single one goes over Discord's field limits."""
    embeds = []
    current = discord.Embed(
        title=f"📌 Archived Pins — #{source_channel.name}",
        color=discord.Color.gold(),
        timestamp=datetime.now(timezone.utc),
    )
    field_count = 0

    for msg in pins:
        content = trim(msg.content) if msg.content else "*(no text - attachment/embed only)*"
        value = f"{content}\n[Jump to message]({msg.jump_url})"
        name = f"{msg.author.display_name} — {msg.created_at.strftime('%d %b %Y')}"

        if field_count >= 24:
            embeds.append(current)
            current = discord.Embed(
                title=f"📌 Archived Pins — #{source_channel.name} (cont.)",
                color=discord.Color.gold(),
                timestamp=datetime.now(timezone.utc),
            )
            field_count = 0

        current.add_field(name=name[:256], value=value[:1024], inline=False)
        field_count += 1

    embeds.append(current)
    embeds[-1].set_footer(text=f"{len(pins)} pinned message(s) archived")
    return embeds


class Archive(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    archive_group = app_commands.Group(name="archive", description="Archive and clear a channel's pinned messages")

    @archive_group.command(name="setchannel", description="Set where archive summaries get posted by default")
    @app_commands.describe(channel="The channel archive summaries should be posted to")
    async def setchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        data = load_data()
        data["archive_channel_id"] = channel.id
        save_data(data)
        await interaction.response.send_message(
            f"✅ Archive summaries will now be posted to {channel.mention} by default.", ephemeral=True
        )

    @archive_group.command(name="pins", description="Archive and unpin everything currently pinned in this channel")
    @app_commands.describe(destination="Optional - post the summary here instead of the default archive channel")
    async def pins(self, interaction: discord.Interaction, destination: discord.TextChannel = None):
        await interaction.response.defer(thinking=True, ephemeral=True)

        source_channel = interaction.channel
        pinned = await source_channel.pins()

        if not pinned:
            await interaction.followup.send("There's nothing pinned in this channel.", ephemeral=True)
            return

        data = load_data()
        target_channel = destination
        if target_channel is None and data.get("archive_channel_id"):
            target_channel = self.bot.get_channel(data["archive_channel_id"])
        if target_channel is None:
            target_channel = source_channel

        pinned_sorted = sorted(pinned, key=lambda m: m.created_at)
        embeds = build_archive_embeds(source_channel, pinned_sorted)

        for embed in embeds:
            await target_channel.send(embed=embed)

        unpinned_count = 0
        for msg in pinned_sorted:
            try:
                await msg.unpin(reason=f"Archived by {interaction.user}")
                unpinned_count += 1
            except discord.HTTPException:
                pass

        data["runs"].append({
            "source_channel_id": source_channel.id,
            "target_channel_id": target_channel.id,
            "archived_by": interaction.user.id,
            "pin_count": len(pinned_sorted),
            "archived_at": int(datetime.now(timezone.utc).timestamp()),
        })
        save_data(data)

        await interaction.followup.send(
            f"✅ Archived {len(pinned_sorted)} pinned message(s) to {target_channel.mention} "
            f"and unpinned {unpinned_count} of them.",
            ephemeral=True,
        )

    @archive_group.command(name="history", description="See past archive runs")
    async def history(self, interaction: discord.Interaction):
        data = load_data()
        runs = data.get("runs", [])

        if not runs:
            await interaction.response.send_message("No archive runs recorded yet.", ephemeral=True)
            return

        lines = []
        for run in runs[-10:][::-1]:
            source = f"<#{run['source_channel_id']}>"
            target = f"<#{run['target_channel_id']}>"
            lines.append(f"<t:{run['archived_at']}:R> — {run['pin_count']} pin(s) from {source} → {target}")

        embed = discord.Embed(
            title="🗂️ Archive History",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        embed.set_footer(text="Showing the 10 most recent runs")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Archive(bot))
