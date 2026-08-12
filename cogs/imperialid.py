"""
/imperial-id command
------------------
Fun command - generates a personalized "Imperial ID card" style embed for a
member. The ID number and clearance level are randomized but seeded off the
member's Discord ID, so the same person always gets the same card.
"""

import random
import discord
from discord import app_commands
from discord.ext import commands

CLEARANCE_LEVELS = [
    "Alpha", "Beta", "Gamma", "Delta", "Omega",
]


def top_role_name(member: discord.Member) -> str:
    # Highest non-@everyone role, or a fallback if they only have @everyone
    roles = [r for r in member.roles if r.name != "@everyone"]
    if not roles:
        return "Unranked Citizen"
    return max(roles, key=lambda r: r.position).name


class ImperialID(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="imperial-id", description="Generate your (or someone else's) Imperial ID card")
    @app_commands.describe(member="Optional - whose ID card to generate. Defaults to you.")
    async def imperial_id(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user

        # Seeded on the member's ID so their card details stay consistent every time
        rng = random.Random(target.id)
        id_number = f"{rng.randint(1000, 9999)}-{rng.randint(100, 999)}-{rng.randint(10, 99)}"
        clearance = rng.choice(CLEARANCE_LEVELS)

        embed = discord.Embed(
            title="🪖 IMPERIAL IDENTIFICATION",
            color=discord.Color.dark_grey(),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Name", value=target.display_name, inline=True)
        embed.add_field(name="Designation", value=top_role_name(target), inline=True)
        embed.add_field(name="Clearance", value=f"Level {clearance}", inline=True)
        embed.add_field(name="ID Number", value=f"`{id_number}`", inline=True)
        if target.joined_at:
            embed.add_field(name="Enlisted", value=f"<t:{int(target.joined_at.timestamp())}:D>", inline=True)
        embed.set_footer(text="Property of the Galactic Empire. Report loss immediately.")

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(ImperialID(bot))