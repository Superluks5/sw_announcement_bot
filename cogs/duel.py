"""
/duel command
------------------
Fun roleplay command - simulates a duel between two members with a
randomized weapon and outcome. Same lightweight pattern as /wanted.
"""

import random
import discord
from discord import app_commands
from discord.ext import commands

WEAPONS = [
    "a lightsaber",
    "a blaster pistol",
    "a vibroblade",
    "a heavy repeating blaster",
    "an ion rifle",
    "a pair of hidden vibro-daggers",
    "a borrowed E-11 blaster rifle",
]

WIN_LINES = [
    "{winner} lands the decisive blow and {loser} hits the ground hard.",
    "{winner} outmaneuvers {loser} completely - it's over in seconds.",
    "After a tense standoff, {winner} strikes first and {loser} goes down.",
    "{loser} never saw it coming - {winner} wins cleanly.",
    "{winner} disarms {loser} and claims victory without breaking a sweat.",
]

DRAW_LINES = [
    "Both combatants collapse from exhaustion. Officially a draw.",
    "Neither {a} nor {b} could land a finishing blow. Draw.",
    "A nearby patrol interrupts the duel before a winner emerges.",
]


class Duel(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="duel", description="Challenge another member to a simulated duel")
    @app_commands.describe(opponent="Who are you dueling?")
    async def duel(self, interaction: discord.Interaction, opponent: discord.Member):
        challenger = interaction.user

        if opponent.id == challenger.id:
            await interaction.response.send_message(
                "⚔️ You can't duel yourself - unless this is some kind of clone trick.",
                ephemeral=True,
            )
            return

        if opponent.bot:
            await interaction.response.send_message(
                "⚔️ Dueling a droid feels like cheating. Pick a real opponent.",
                ephemeral=True,
            )
            return

        weapon = random.choice(WEAPONS)
        roll = random.random()

        if roll < 0.08:
            description = random.choice(DRAW_LINES).format(a=challenger.display_name, b=opponent.display_name)
            color = discord.Color.light_grey()
        else:
            winner, loser = (challenger, opponent) if random.random() < 0.5 else (opponent, challenger)
            description = random.choice(WIN_LINES).format(winner=winner.mention, loser=loser.mention)
            color = discord.Color.dark_red()

        embed = discord.Embed(
            title="⚔️ Duel!",
            description=(
                f"{challenger.mention} challenges {opponent.mention}, "
                f"weapon of choice: **{weapon}**.\n\n{description}"
            ),
            color=color,
        )

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Duel(bot))