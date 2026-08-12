"""
/inactivity command  (restricted via permissions.py)
------------------
Tracks the last time each member sent a message (timestamp only - no message
content is read or stored), and lets authorized roles pull a list of members
who haven't been active in X days. Useful for rank reviews / activity checks.

Note: only tracks activity from whenever this cog was first loaded onward -
members with no recorded activity yet are listed separately, since we have
no history for them.

Who can use this command is controlled centrally in /permissions.py, not here.
"""

import os
import json
import time
import discord
from discord import app_commands
from discord.ext import commands

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "activity_data.json")


def load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        return {"last_seen": {}}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("last_seen", {})
    return data


def save_data(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


class Inactivity(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        data = load_data()
        data["last_seen"][str(message.author.id)] = int(time.time())
        save_data(data)

    @app_commands.command(name="inactivity", description="List members inactive for X+ days")
    @app_commands.describe(days="Flag members with no messages in at least this many days")
    async def inactivity(self, interaction: discord.Interaction, days: int = 14):
        await interaction.response.defer()

        data = load_data()
        last_seen = data["last_seen"]
        cutoff = time.time() - (days * 86400)

        inactive = []
        never_tracked = []

        for member in interaction.guild.members:
            if member.bot:
                continue
            ts = last_seen.get(str(member.id))
            if ts is None:
                never_tracked.append(member)
            elif ts < cutoff:
                inactive.append((member, ts))

        inactive.sort(key=lambda pair: pair[1])  # oldest activity first

        embed = discord.Embed(
            title=f"📉 Inactivity Report — {days}+ days",
            color=discord.Color.dark_orange(),
        )

        if inactive:
            lines = [f"<@{m.id}> — last active <t:{ts}:R>" for m, ts in inactive[:25]]
            embed.add_field(name=f"Inactive ({len(inactive)})", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Inactive", value="*Nobody meets this threshold.*", inline=False)

        if never_tracked:
            names = ", ".join(m.mention for m in never_tracked[:15])
            extra = f" (+{len(never_tracked) - 15} more)" if len(never_tracked) > 15 else ""
            embed.add_field(
                name=f"No activity recorded yet ({len(never_tracked)})",
                value=f"{names}{extra}\n*No messages seen since tracking started.*",
                inline=False,
            )

        embed.set_footer(text="Activity tracking only counts messages sent since this feature was added.")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Inactivity(bot))