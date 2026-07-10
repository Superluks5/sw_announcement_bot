"""
/roadmap command group
------------------------
Lets owners/staff maintain a running development roadmap. One "live" message
is tracked (created via /roadmap show) and automatically edited whenever
items are added, removed, or cleared - so it always stays current without
needing to repost.

Subcommands:
  /roadmap add     - add an item to Planned / In Progress / Done
  /roadmap remove  - remove an item by its number
  /roadmap show    - post (or move) the live roadmap message to this channel
  /roadmap clear   - wipe all items in a category
"""

import os
import json
import discord
from discord import app_commands
from discord.ext import commands

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "roadmap_data.json")

CATEGORIES = {
    "planned": "🗓️ Planned",
    "in_progress": "🚧 In Progress",
    "done": "✅ Done",
}

DEFAULT_DATA = {
    "planned": [],
    "in_progress": [],
    "done": [],
    "channel_id": None,
    "message_id": None,
}


def load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        return dict(DEFAULT_DATA)
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    for key, default in DEFAULT_DATA.items():
        data.setdefault(key, default)
    return data


def save_data(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def build_roadmap_embed(data: dict) -> discord.Embed:
    embed = discord.Embed(
        title="🛰️ Development Roadmap",
        color=discord.Color.blurple(),
    )
    for key, label in CATEGORIES.items():
        items = data.get(key, [])
        if items:
            lines = [f"`{i+1}.` {item}" for i, item in enumerate(items)]
            value = "\n".join(lines)
        else:
            value = "*Nothing here yet.*"
        embed.add_field(name=label, value=value, inline=False)
    embed.set_footer(text="Updates automatically when items are added or removed.")
    return embed


category_choices = [
    app_commands.Choice(name=label, value=key) for key, label in CATEGORIES.items()
]


class Roadmap(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    roadmap_group = app_commands.Group(name="roadmap", description="Manage and post the development roadmap")

    async def refresh_live_message(self, data: dict):
        """Edit the tracked live roadmap message, if one exists and is still reachable."""
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

        embed = build_roadmap_embed(data)
        await message.edit(embed=embed)
        return True

    @roadmap_group.command(name="add", description="Add an item to the roadmap")
    @app_commands.describe(category="Which section to add to", item="The item text, e.g. 'New planet: Hoth'")
    @app_commands.choices(category=category_choices)
    async def add(self, interaction: discord.Interaction, category: app_commands.Choice[str], item: str):
        data = load_data()
        data[category.value].append(item)
        save_data(data)
        updated_live = await self.refresh_live_message(data)

        note = "" if updated_live else "\n*(No live roadmap message set yet - use `/roadmap show` in a channel first.)*"
        await interaction.response.send_message(
            f"✅ Added to **{CATEGORIES[category.value]}**: {item}{note}", ephemeral=True
        )

    @roadmap_group.command(name="remove", description="Remove an item from the roadmap by its number")
    @app_commands.describe(category="Which section to remove from", number="The item number (see /roadmap show)")
    @app_commands.choices(category=category_choices)
    async def remove(self, interaction: discord.Interaction, category: app_commands.Choice[str], number: int):
        data = load_data()
        items = data[category.value]
        if number < 1 or number > len(items):
            await interaction.response.send_message(
                f"⚠️ There's no item #{number} in **{CATEGORIES[category.value]}**. "
                f"Use `/roadmap show` to see current numbers.",
                ephemeral=True,
            )
            return
        removed = items.pop(number - 1)
        save_data(data)
        updated_live = await self.refresh_live_message(data)

        note = "" if updated_live else "\n*(No live roadmap message set yet - use `/roadmap show` in a channel first.)*"
        await interaction.response.send_message(
            f"🗑️ Removed from **{CATEGORIES[category.value]}**: {removed}{note}", ephemeral=True
        )

    @roadmap_group.command(name="clear", description="Clear all items in a category")
    @app_commands.describe(category="Which section to clear")
    @app_commands.choices(category=category_choices)
    async def clear(self, interaction: discord.Interaction, category: app_commands.Choice[str]):
        data = load_data()
        data[category.value] = []
        save_data(data)
        updated_live = await self.refresh_live_message(data)

        note = "" if updated_live else "\n*(No live roadmap message set yet - use `/roadmap show` in a channel first.)*"
        await interaction.response.send_message(
            f"🧹 Cleared **{CATEGORIES[category.value]}**.{note}", ephemeral=True
        )

    @roadmap_group.command(name="show", description="Post (or move) the live roadmap message to this channel")
    async def show(self, interaction: discord.Interaction):
        data = load_data()
        embed = build_roadmap_embed(data)
        await interaction.response.send_message(embed=embed)
        sent_message = await interaction.original_response()

        # Track this as the new "live" message - future add/remove/clear will edit it
        data["channel_id"] = interaction.channel_id
        data["message_id"] = sent_message.id
        save_data(data)


async def setup(bot: commands.Bot):
    await bot.add_cog(Roadmap(bot))