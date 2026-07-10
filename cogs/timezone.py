"""
/timezone command
------------------
Type a time + pick your timezone, and this posts:
1. A Discord auto-timestamp (shows correctly in everyone's own local time automatically)
2. A few manual reference conversions for common regions in your community

Requires the "tzdata" package on Windows (zoneinfo needs it there).
"""

import random
from datetime import datetime, date
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

# Common regions - tweak this list to match your community's spread
REGIONS = {
    "riga": ("Latvia (Riga)", "Europe/Riga"),
    "london": ("UK (London)", "Europe/London"),
    "berlin": ("Central Europe (Berlin)", "Europe/Berlin"),
    "moscow": ("Russia (Moscow)", "Europe/Moscow"),
    "us_east": ("US East", "America/New_York"),
    "us_west": ("US West", "America/Los_Angeles"),
    "india": ("India", "Asia/Kolkata"),
    "australia": ("Australia (Sydney)", "Australia/Sydney"),
}


class Timezone(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="timezone", description="Convert a time to everyone's local time + a few regions")
    @app_commands.describe(
        time="Time in 24h format, e.g. 18:00 or 9:30",
        your_timezone="The timezone your typed time is in",
        date_str="Optional date (YYYY-MM-DD). Defaults to today.",
    )
    @app_commands.choices(
        your_timezone=[
            app_commands.Choice(name=label, value=key) for key, (label, _) in REGIONS.items()
        ]
    )
    async def timezone(
        self,
        interaction: discord.Interaction,
        time: str,
        your_timezone: app_commands.Choice[str],
        date_str: str = None,
    ):
        try:
            hour_str, minute_str = time.strip().split(":")
            hour, minute = int(hour_str), int(minute_str)
        except (ValueError, IndexError):
            await interaction.response.send_message(
                "⚠️ Couldn't read that time. Use 24h format like `18:00` or `9:30`.",
                ephemeral=True,
            )
            return

        if date_str:
            try:
                target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                await interaction.response.send_message(
                    "⚠️ Couldn't read that date. Use the format `YYYY-MM-DD`, e.g. `2026-07-15`.",
                    ephemeral=True,
                )
                return
        else:
            target_date = date.today()

        source_key = your_timezone.value
        _, source_tz_name = REGIONS[source_key]
        source_tz = ZoneInfo(source_tz_name)

        try:
            local_dt = datetime(
                target_date.year, target_date.month, target_date.day, hour, minute, tzinfo=source_tz
            )
        except ValueError:
            await interaction.response.send_message(
                "⚠️ That's not a valid time (hour 0-23, minute 0-59).", ephemeral=True
            )
            return

        unix_ts = int(local_dt.timestamp())

        # Build reference conversions for the other regions
        lines = []
        for key, (label, tz_name) in REGIONS.items():
            converted = local_dt.astimezone(ZoneInfo(tz_name))
            lines.append(f"**{label}:** {converted.strftime('%H:%M, %a %d %b')}")

        reference_block = "\n".join(lines)

        message = f"""🕒 **Time Conversion**

<t:{unix_ts}:F>  (shows automatically in your own local time)
Relative: <t:{unix_ts}:R>

**Reference times:**
{reference_block}"""

        await interaction.response.send_message(message)


async def setup(bot: commands.Bot):
    await bot.add_cog(Timezone(bot))
