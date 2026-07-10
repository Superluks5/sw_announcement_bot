"""
/revenue command group
------------------------
Simple revenue log for tracking game/server income over time (Robux,
gamepasses, ad revenue, sponsorships, etc). Data saved locally in JSON.

Subcommands:
  /revenue log    - log a new revenue entry
  /revenue show   - see totals (all time / this month / this year) + breakdown by source
  /revenue remove - remove a specific entry by its number
  /revenue clear  - wipe the whole log
"""

import os
import json
from datetime import datetime, date
import discord
from discord import app_commands
from discord.ext import commands

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "revenue_data.json")
CURRENCY_UNIT = "Robux"  # change this if you track a different currency


def load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        return {"entries": []}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("entries", [])
    return data


def save_data(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


PERIOD_CHOICES = [
    app_commands.Choice(name="All time", value="all"),
    app_commands.Choice(name="This month", value="month"),
    app_commands.Choice(name="This year", value="year"),
]


def filter_by_period(entries: list, period: str) -> list:
    if period == "all":
        return entries
    today = date.today()
    filtered = []
    for e in entries:
        entry_date = datetime.strptime(e["date"], "%Y-%m-%d").date()
        if period == "month" and entry_date.year == today.year and entry_date.month == today.month:
            filtered.append(e)
        elif period == "year" and entry_date.year == today.year:
            filtered.append(e)
    return filtered


class Revenue(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    revenue_group = app_commands.Group(name="revenue", description="Track game/server revenue over time")

    @revenue_group.command(name="log", description="Log a new revenue entry")
    @app_commands.describe(
        amount=f"Amount earned (in {CURRENCY_UNIT})",
        source="Where it came from, e.g. 'Gamepasses', 'Ad revenue', 'Sponsorship'",
        note="Optional extra note",
    )
    async def log(self, interaction: discord.Interaction, amount: float, source: str, note: str = ""):
        data = load_data()
        data["entries"].append({
            "amount": amount,
            "source": source,
            "note": note,
            "date": date.today().isoformat(),
            "logged_by": interaction.user.display_name,
        })
        save_data(data)
        await interaction.response.send_message(
            f"✅ Logged **{amount:,.2f} {CURRENCY_UNIT}** from **{source}**.", ephemeral=True
        )

    @revenue_group.command(name="show", description="See revenue totals and breakdown by source")
    @app_commands.describe(period="Which timeframe to show")
    @app_commands.choices(period=PERIOD_CHOICES)
    async def show(self, interaction: discord.Interaction, period: app_commands.Choice[str] = None):
        data = load_data()
        period_value = period.value if period else "all"
        entries = filter_by_period(data["entries"], period_value)

        if not entries:
            await interaction.response.send_message("No revenue logged for that period yet.", ephemeral=True)
            return

        total = sum(e["amount"] for e in entries)

        by_source = {}
        for e in entries:
            by_source[e["source"]] = by_source.get(e["source"], 0) + e["amount"]

        breakdown_lines = [f"• **{src}:** {amt:,.2f} {CURRENCY_UNIT}" for src, amt in sorted(by_source.items(), key=lambda x: -x[1])]

        period_label = {"all": "All time", "month": "This month", "year": "This year"}[period_value]

        embed = discord.Embed(
            title=f"💰 Revenue — {period_label}",
            description=f"**Total: {total:,.2f} {CURRENCY_UNIT}**\n\n" + "\n".join(breakdown_lines),
            color=discord.Color.green(),
        )
        embed.set_footer(text=f"{len(entries)} entries")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @revenue_group.command(name="remove", description="Remove a revenue entry by its number (most recent = 1)")
    @app_commands.describe(number="Entry number, counting from the most recent (1 = latest)")
    async def remove(self, interaction: discord.Interaction, number: int):
        data = load_data()
        entries = data["entries"]
        recent_first = list(reversed(entries))

        if number < 1 or number > len(recent_first):
            await interaction.response.send_message(
                f"⚠️ There's no entry #{number}. There are {len(entries)} entries logged.", ephemeral=True
            )
            return

        target = recent_first[number - 1]
        entries.remove(target)
        save_data(data)
        await interaction.response.send_message(
            f"🗑️ Removed: {target['amount']:,.2f} {CURRENCY_UNIT} from {target['source']} ({target['date']})",
            ephemeral=True,
        )

    @revenue_group.command(name="clear", description="Wipe the entire revenue log")
    async def clear(self, interaction: discord.Interaction):
        save_data({"entries": []})
        await interaction.response.send_message("🧹 Revenue log cleared.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Revenue(bot))
