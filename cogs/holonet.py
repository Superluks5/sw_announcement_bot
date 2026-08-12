"""
/holonet command
------------------
Fun command - posts a random Star Wars trivia/lore fact, styled as an
intercepted Holonet transmission. Same lightweight pattern as /wanted.
"""

import random
import discord
from discord import app_commands
from discord.ext import commands

FACTS = [
    "Order 66 relied on inhibitor chips implanted in clone troopers to force their compliance.",
    "The Death Star's critical weakness was a two-meter-wide thermal exhaust port leading straight to its reactor core.",
    "Standard stormtrooper armor offered surprisingly little protection against direct blaster fire.",
    "Wookiees are native to the dense forest moon of Kashyyyk and are known for exceptional physical strength.",
    "The Force is traditionally described in two aspects: a light side and a dark side.",
    "Imperial Navy officer ranks were loosely modeled on real-world naval command structures.",
    "TIE fighters trade deflector shields for speed and maneuverability, making them fast but fragile.",
    "For a long stretch of galactic history, the Sith operated under a strict Rule of Two: one master, one apprentice.",
    "Darth Vader's iconic suit doubles as life support, keeping him alive after catastrophic injuries.",
    "Coruscant, the Imperial capital, is a planet almost entirely covered by a single continuous city.",
    "Grand Admiral is one of the rarest and most prestigious ranks in the entire Imperial Navy.",
    "Lightsaber blades are generated using a focusing crystal, commonly known as a kyber crystal.",
    "The Empire maintained notoriously strict recruitment and training standards for its stormtrooper corps.",
    "Hyperspace travel lets starships cross vast distances by routing around normal space entirely.",
    "Many Imperial-class Star Destroyers doubled as mobile command centers for entire sectors.",
    "Bounty hunters were frequently contracted by the Empire for jobs official channels preferred to avoid.",
    "An Imperial officer's rank is typically displayed on a small rectangular chest plaque, not shoulder insignia.",
    "Non-human species faced widespread discrimination within the Empire's military ranks.",
    "The Emperor ruled through a calculated mix of fear, propaganda, and overwhelming military might.",
    "Many Imperial vessels were named after historical Imperial figures, victories, or ideological concepts.",
]


class Holonet(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="holonet", description="Pull up a random Star Wars fact from the Holonet")
    async def holonet(self, interaction: discord.Interaction):
        fact = random.choice(FACTS)

        embed = discord.Embed(
            title="📡 Holonet Transmission Intercepted",
            description=fact,
            color=discord.Color.dark_red(),
        )
        embed.set_footer(text="Signal source: unknown. Use responsibly, citizen.")

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Holonet(bot))