"""
/roadmap command group
------------------------
Tracks a development roadmap grouped by AREA (e.g. Discord Development,
Game Development) and STATUS (Planned / In Progress / Done) for each item.
One "live" message is tracked (set via /roadmap show) and automatically
edited whenever items are added, removed, or cleared.

Subcommands:
  /roadmap add     - add an item under an area + status
  /roadmap remove  - remove an item by its number (numbers shown in /roadmap show)
  /roadmap move    - change an item's status (e.g. Planned -> Done) by its number
  /roadmap show    - post (or move) the live roadmap message to this channel
  /roadmap clear   - wipe all items under an area + status
"""

import os
import json
import discord
from discord import app_commands
from discord.ext import commands, tasks

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "roadmap_data.json")

# Add/remove/rename areas here to fit your project - no other code needs to change
AREAS = {
    "discord_dev": "🤖 Discord Development",
    "game_dev": "🎮 Game Development",
    "general": "📋 General",
}

STATUSES = {
    "planned": "🗓️ Planned",
    "in_progress": "🚧 In Progress",
    "done": "✅ Done",
}

DEFAULT_DATA = {
    "items": [],  # each item: {"area": str, "status": str, "text": str}
    "channel_id": None,
    "message_id": None,
}


def load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        return {"items": [], "channel_id": None, "message_id": None}

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Migrate old flat format (planned/in_progress/done as plain lists) if present
    if "items" not in data:
        migrated_items = []
        for status_key in STATUSES:
            for text in data.get(status_key, []):
                migrated_items.append({"area": "general", "status": status_key, "text": text})
        data = {
            "items": migrated_items,
            "channel_id": data.get("channel_id"),
            "message_id": data.get("message_id"),
        }

    data.setdefault("items", [])
    data.setdefault("channel_id", None)
    data.setdefault("message_id", None)
    return data


def save_data(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def build_roadmap_embed(data: dict) -> discord.Embed:
    embed = discord.Embed(
        title="🛰️ Development Roadmap",
        color=discord.Color.blurple(),
    )

    items = data.get("items", [])

    for area_key, area_label in AREAS.items():
        area_items = [item for item in items if item["area"] == area_key]

        if not area_items:
            continue  # skip areas with nothing in them at all

        lines = []
        counter = 1
        for status_key, status_label in STATUSES.items():
            status_items = [item for item in area_items if item["status"] == status_key]
            if not status_items:
                continue
            lines.append(f"**{status_label}**")
            for item in status_items:
                lines.append(f"`{counter}.` {item['text']}")
                counter += 1

        embed.add_field(name=area_label, value="\n".join(lines), inline=False)

    if not embed.fields:
        embed.description = "*Nothing on the roadmap yet.*"

    embed.set_footer(text="Updates automatically when items are added or removed.")
    return embed


def get_numbered_items(data: dict, area_key: str):
    """Return the items for one area, in the same numbered order shown in the embed."""
    area_items = [item for item in data["items"] if item["area"] == area_key]
    ordered = []
    for status_key in STATUSES:
        ordered.extend([item for item in area_items if item["status"] == status_key])
    return ordered


area_choices = [app_commands.Choice(name=label, value=key) for key, label in AREAS.items()]
status_choices = [app_commands.Choice(name=label, value=key) for key, label in STATUSES.items()]


class Roadmap(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._last_mtime = None
        self.watch_for_changes.start()

    def cog_unload(self):
        self.watch_for_changes.cancel()

    @tasks.loop(seconds=5)
    async def watch_for_changes(self):
        """Picks up edits made from anywhere - not just Discord commands, but
        also the web dashboard writing roadmap_data.json directly - and keeps
        the live Discord message in sync within a few seconds either way."""
        if not os.path.exists(DATA_FILE):
            return

        mtime = os.path.getmtime(DATA_FILE)
        if self._last_mtime is None:
            self._last_mtime = mtime  # first run - just record it, don't refresh yet
            return

        if mtime != self._last_mtime:
            self._last_mtime = mtime
            data = load_data()
            await self.refresh_live_message(data)

    @watch_for_changes.before_loop
    async def before_watch(self):
        await self.bot.wait_until_ready()

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

        await message.edit(embed=build_roadmap_embed(data))
        return True

    @roadmap_group.command(name="add", description="Add an item to the roadmap")
    @app_commands.describe(
        area="Which project area this belongs to",
        status="Current status of this item",
        item="The item text, e.g. 'Add /shoutout command'",
    )
    @app_commands.choices(area=area_choices, status=status_choices)
    async def add(
        self,
        interaction: discord.Interaction,
        area: app_commands.Choice[str],
        status: app_commands.Choice[str],
        item: str,
    ):
        data = load_data()
        data["items"].append({"area": area.value, "status": status.value, "text": item})
        save_data(data)
        updated_live = await self.refresh_live_message(data)

        note = "" if updated_live else "\n*(No live roadmap message set yet - use `/roadmap show` in a channel first.)*"
        await interaction.response.send_message(
            f"✅ Added to **{AREAS[area.value]} → {STATUSES[status.value]}**: {item}{note}",
            ephemeral=True,
        )

    @roadmap_group.command(name="remove", description="Remove an item from the roadmap by its number")
    @app_commands.describe(
        area="Which project area to remove from",
        number="The item number for this area (see /roadmap show)",
    )
    @app_commands.choices(area=area_choices)
    async def remove(self, interaction: discord.Interaction, area: app_commands.Choice[str], number: int):
        data = load_data()
        ordered = get_numbered_items(data, area.value)

        if number < 1 or number > len(ordered):
            await interaction.response.send_message(
                f"⚠️ There's no item #{number} in **{AREAS[area.value]}**. "
                f"Use `/roadmap show` to see current numbers.",
                ephemeral=True,
            )
            return

        target = ordered[number - 1]
        data["items"].remove(target)
        save_data(data)
        updated_live = await self.refresh_live_message(data)

        note = "" if updated_live else "\n*(No live roadmap message set yet - use `/roadmap show` in a channel first.)*"
        await interaction.response.send_message(
            f"🗑️ Removed from **{AREAS[area.value]}**: {target['text']}{note}", ephemeral=True
        )

    @roadmap_group.command(name="move", description="Change an item's status, e.g. move it from Planned to Done")
    @app_commands.describe(
        area="Which project area the item is in",
        number="The item number for this area (see /roadmap show)",
        status="The new status to move it to",
    )
    @app_commands.choices(area=area_choices, status=status_choices)
    async def move(
        self,
        interaction: discord.Interaction,
        area: app_commands.Choice[str],
        number: int,
        status: app_commands.Choice[str],
    ):
        data = load_data()
        ordered = get_numbered_items(data, area.value)

        if number < 1 or number > len(ordered):
            await interaction.response.send_message(
                f"⚠️ There's no item #{number} in **{AREAS[area.value]}**. "
                f"Use `/roadmap show` to see current numbers.",
                ephemeral=True,
            )
            return

        target = ordered[number - 1]

        if target["status"] == status.value:
            await interaction.response.send_message(
                f"ℹ️ **{target['text']}** is already **{STATUSES[status.value]}**.",
                ephemeral=True,
            )
            return

        old_status = target["status"]
        target["status"] = status.value
        save_data(data)
        updated_live = await self.refresh_live_message(data)

        note = "" if updated_live else "\n*(No live roadmap message set yet - use `/roadmap show` in a channel first.)*"
        await interaction.response.send_message(
            f"🔀 Moved **{target['text']}**: {STATUSES[old_status]} → {STATUSES[status.value]}{note}",
            ephemeral=True,
        )

    @roadmap_group.command(name="clear", description="Clear all items in an area (optionally just one status)")
    @app_commands.describe(
        area="Which project area to clear",
        status="Optional - only clear this status. Leave blank to clear the whole area.",
    )
    @app_commands.choices(area=area_choices, status=status_choices)
    async def clear(
        self,
        interaction: discord.Interaction,
        area: app_commands.Choice[str],
        status: app_commands.Choice[str] = None,
    ):
        data = load_data()
        if status:
            data["items"] = [
                i for i in data["items"] if not (i["area"] == area.value and i["status"] == status.value)
            ]
            label = f"{AREAS[area.value]} → {STATUSES[status.value]}"
        else:
            data["items"] = [i for i in data["items"] if i["area"] != area.value]
            label = AREAS[area.value]

        save_data(data)
        updated_live = await self.refresh_live_message(data)

        note = "" if updated_live else "\n*(No live roadmap message set yet - use `/roadmap show` in a channel first.)*"
        await interaction.response.send_message(f"🧹 Cleared **{label}**.{note}", ephemeral=True)

    @roadmap_group.command(name="show", description="Post (or move) the live roadmap message to this channel")
    async def show(self, interaction: discord.Interaction):
        data = load_data()
        embed = build_roadmap_embed(data)
        await interaction.response.send_message(embed=embed)
        sent_message = await interaction.original_response()

        data["channel_id"] = interaction.channel_id
        data["message_id"] = sent_message.id
        save_data(data)


async def setup(bot: commands.Bot):
    await bot.add_cog(Roadmap(bot))