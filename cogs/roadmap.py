"""
/roadmap command group
------------------------
Lets owners/staff maintain a running development roadmap and post/update it
publicly. Data is saved to a local JSON file so it persists between restarts.

Subcommands:
  /roadmap add     - add an item to Planned / In Progress / Done
  /roadmap remove  - remove an item by its number
  /roadmap show    - post the roadmap publicly (numbered, so remove is easy)
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


def load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        return {key: [] for key in CATEGORIES}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    for key in CATEGORIES:
        data.setdefault(key, [])
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
    return embed


category_choices = [
    app_commands.Choice(name=label, value=key) for key, label in CATEGORIES.items()
]


class Roadmap(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    roadmap_group = app_commands.Group(name="roadmap", description="Manage and post the development roadmap")

    @roadmap_group.command(name="add", description="Add an item to the roadmap")
    @app_commands.describe(category="Which section to add to", item="The item text, e.g. 'New planet: Hoth'")
    @app_commands.choices(category=category_choices)
    async def add(self, interaction: discord.Interaction, category: app_commands.Choice[str], item: str):
        data = load_data()
        data[category.value].append(item)
        save_data(data)
        await interaction.response.send_message(
            f"✅ Added to **{CATEGORIES[category.value]}**: {item}", ephemeral=True
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
        await interaction.response.send_message(
            f"🗑️ Removed from **{CATEGORIES[category.value]}**: {removed}", ephemeral=True
        )

    @roadmap_group.command(name="clear", description="Clear all items in a category")
    @app_commands.describe(category="Which section to clear")
    @app_commands.choices(category=category_choices)
    async def clear(self, interaction: discord.Interaction, category: app_commands.Choice[str]):
        data = load_data()
        data[category.value] = []
        save_data(data)
        await interaction.response.send_message(
            f"🧹 Cleared **{CATEGORIES[category.value]}**.", ephemeral=True
        )

    @roadmap_group.command(name="show", description="Post the current roadmap publicly")
    async def show(self, interaction: discord.Interaction):
        data = load_data()
        embed = build_roadmap_embed(data)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Roadmap(bot))