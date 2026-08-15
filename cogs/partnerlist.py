"""
/partner command group
------------------------
Maintains a directory of partnered servers/creators, posted as a "live"
message that auto-updates whenever a partner is added or removed - same
pattern as /roadmap and /team.

Subcommands:
  /partner add    - add a partner with a name, link, and optional note
  /partner remove - remove a partner by its number
  /partner show   - post (or move) the live directory message to this channel
  /partner clear  - wipe the whole directory
"""

import os
import json
import discord
from discord import app_commands
from discord.ext import commands, tasks

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "partner_data.json")


def load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        return {"partners": [], "channel_id": None, "message_id": None}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("partners", [])
    data.setdefault("channel_id", None)
    data.setdefault("message_id", None)
    return data


def save_data(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def build_partner_embed(data: dict) -> discord.Embed:
    embed = discord.Embed(title="🤝 Partnered Servers & Creators", color=discord.Color.purple())

    if not data["partners"]:
        embed.description = "*No partners listed yet.*"
    else:
        lines = []
        for i, p in enumerate(data["partners"]):
            entry = f"`{i+1}.` **{p['name']}** — {p['link']}"
            if p.get("note"):
                entry += f"\n     _{p['note']}_"
            lines.append(entry)
        embed.description = "\n".join(lines)

    embed.set_footer(text="Updates automatically when partners are added or removed.")
    return embed


class PartnerList(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._last_mtime = None
        self.watch_for_changes.start()

    def cog_unload(self):
        self.watch_for_changes.cancel()

    @tasks.loop(seconds=5)
    async def watch_for_changes(self):
        if not os.path.exists(DATA_FILE):
            return
        mtime = os.path.getmtime(DATA_FILE)
        if self._last_mtime is None:
            self._last_mtime = mtime
            return
        if mtime != self._last_mtime:
            self._last_mtime = mtime
            data = load_data()
            await self.refresh_live_message(data)

    @watch_for_changes.before_loop
    async def before_watch(self):
        await self.bot.wait_until_ready()

    partner_group = app_commands.Group(name="partner", description="Manage and post the partner directory")

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

        await message.edit(embed=build_partner_embed(data))
        return True

    @partner_group.command(name="add", description="Add a partnered server/creator to the directory")
    @app_commands.describe(
        name="Partner's name",
        link="Invite link or channel/profile link",
        note="Optional short note about them",
    )
    async def add(self, interaction: discord.Interaction, name: str, link: str, note: str = ""):
        data = load_data()
        data["partners"].append({"name": name, "link": link, "note": note})
        save_data(data)
        updated_live = await self.refresh_live_message(data)
        note_text = "" if updated_live else "\n*(No live directory message set yet - use `/partner show` in a channel first.)*"
        await interaction.response.send_message(f"✅ Added partner **{name}**.{note_text}", ephemeral=True)

    @partner_group.command(name="remove", description="Remove a partner by its number")
    @app_commands.describe(number="Partner number (see /partner show)")
    async def remove(self, interaction: discord.Interaction, number: int):
        data = load_data()
        partners = data["partners"]

        if number < 1 or number > len(partners):
            await interaction.response.send_message(
                f"⚠️ There's no partner #{number}. Use `/partner show` to see current numbers.", ephemeral=True
            )
            return

        removed = partners.pop(number - 1)
        save_data(data)
        updated_live = await self.refresh_live_message(data)
        note_text = "" if updated_live else "\n*(No live directory message set yet - use `/partner show` in a channel first.)*"
        await interaction.response.send_message(f"🗑️ Removed partner **{removed['name']}**.{note_text}", ephemeral=True)

    @partner_group.command(name="clear", description="Clear the entire partner directory")
    async def clear(self, interaction: discord.Interaction):
        data = load_data()
        data["partners"] = []
        save_data(data)
        updated_live = await self.refresh_live_message(data)
        note_text = "" if updated_live else "\n*(No live directory message set yet - use `/partner show` in a channel first.)*"
        await interaction.response.send_message(f"🧹 Partner directory cleared.{note_text}", ephemeral=True)

    @partner_group.command(name="show", description="Post (or move) the live partner directory to this channel")
    async def show(self, interaction: discord.Interaction):
        data = load_data()
        embed = build_partner_embed(data)
        await interaction.response.send_message(embed=embed)
        sent_message = await interaction.original_response()

        data["channel_id"] = interaction.channel_id
        data["message_id"] = sent_message.id
        save_data(data)


async def setup(bot: commands.Bot):
    await bot.add_cog(PartnerList(bot))
