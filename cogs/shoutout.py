"""
/shoutout command
------------------
Spotlight a community member's fan art, clip, build, or other contribution
in a clean embed. Supports an optional image attachment and an optional
link (e.g. to a YouTube video or Roblox build).
"""

import io
import discord
from discord import app_commands
from discord.ext import commands


class Shoutout(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="shoutout", description="Spotlight a member's fan art, clip, build, or contribution")
    @app_commands.describe(
        member="Who's getting the shoutout?",
        what="What did they make/do? e.g. 'Amazing Death Star fan art'",
        link="Optional link (YouTube video, Roblox build, etc.)",
        image="Optional image to show (fan art, screenshot, etc.)",
    )
    async def shoutout(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        what: str,
        link: str = None,
        image: discord.Attachment = None,
    ):
        embed = discord.Embed(
            title="🌟 Community Shoutout 🌟",
            description=f"**{member.mention}** — {what}",
            color=discord.Color.gold(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        if link:
            embed.add_field(name="Check it out", value=link, inline=False)

        embed.set_footer(text=f"Shared by {interaction.user.display_name}")

        files = []
        if image is not None:
            image_bytes = await image.read()
            file = discord.File(io.BytesIO(image_bytes), filename=image.filename)
            files.append(file)
            embed.set_image(url=f"attachment://{image.filename}")

        await interaction.response.send_message(embed=embed, files=files)


async def setup(bot: commands.Bot):
    await bot.add_cog(Shoutout(bot))