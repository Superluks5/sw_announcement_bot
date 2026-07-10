"""
/wanted command
------------------
Fun roleplay command - generates a "WANTED" bounty poster for a tagged member,
Star Wars bounty-hunter style. Crime and bounty amount are optional; if left
blank, the bot picks something random and silly.
"""

import random
import discord
from discord import app_commands
from discord.ext import commands

RANDOM_CRIMES = [
    "Smuggling spice through an Imperial checkpoint",
    "Impersonating a Jedi Knight without a license",
    "Crashing a landspeeder into the Cantina",
    "Selling counterfeit lightsaber crystals",
    "Unauthorized use of the Force in a public space",
    "Failing to pay a bounty hunter's invoice",
    "Cutting in line at a Mos Eisley food stall",
    "Talking back to a Hutt",
]

BOUNTY_HUNTERS_OFFICE = [
    "Bounty Hunters' Guild",
    "Scum and Villainy Consortium",
    "The Hutt Cartel",
    "Imperial Security Bureau",
]


class Wanted(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="wanted", description="Generate a joke bounty poster for a member")
    @app_commands.describe(
        member="Who's the wanted criminal?",
        crime="Optional - what did they do? Leave blank for a random crime.",
        bounty="Optional - bounty amount in credits. Leave blank for a random amount.",
    )
    async def wanted(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        crime: str = None,
        bounty: int = None,
    ):
        final_crime = crime if crime else random.choice(RANDOM_CRIMES)
        final_bounty = bounty if bounty is not None else random.randint(500, 50000)
        issuer = random.choice(BOUNTY_HUNTERS_OFFICE)

        embed = discord.Embed(
            title="⚠️ WANTED — DEAD OR ALIVE ⚠️",
            description=(
                f"**Target:** {member.mention}\n"
                f"**Crime:** {final_crime}\n"
                f"**Bounty:** {final_bounty:,} credits\n\n"
                f"*Issued by the {issuer}. Approach with caution.*"
            ),
            color=discord.Color.dark_gold(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text="Report sightings to your nearest bounty hunter guild office.")

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Wanted(bot))
