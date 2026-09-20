"""Help command for discovering the bot's main features."""

import os

import discord
from discord import app_commands
from discord.ext import commands


class Help(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Show the bot's available features")
    async def help_command(self, interaction: discord.Interaction):
        dashboard_url = os.environ.get("DASHBOARD_PUBLIC_URL")
        embed = discord.Embed(
            title="📡 Command Help",
            description="Tools for announcements, organization, community management, and economy.",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Community tools",
            value="`/scannounce` · `/broadcast` · `/partner` · `/team`",
            inline=False,
        )
        embed.add_field(
            name="Planning tools",
            value="`/roadmap` · `/taskboard` · `/devlog` · `/versionlog` · `/testflight`",
            inline=False,
        )
        embed.add_field(
            name="Economy and games",
            value="`/work` · `/crime` · `/rob` · `/daily` · `/weekly` · `/balance` · games",
            inline=False,
        )
        embed.add_field(
            name="Moderation and utilities",
            value="`/archive` · `/blocker` · `/inactivity` · `/promote` · `/timezone`",
            inline=False,
        )
        if dashboard_url:
            embed.add_field(name="Dashboard", value=f"[Open the server panel]({dashboard_url})", inline=False)
        embed.set_footer(text="Use Discord's slash-command search for detailed command options.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="status", description="Show the bot's connection status")
    async def status(self, interaction: discord.Interaction):
        latency_ms = round(self.bot.latency * 1000) if self.bot.latency >= 0 else None
        embed = discord.Embed(title="📡 Bot Status", color=discord.Color.green())
        embed.add_field(name="Connection", value="Online", inline=True)
        embed.add_field(name="Latency", value=f"{latency_ms} ms" if latency_ms is not None else "Unknown", inline=True)
        embed.add_field(name="Servers", value=str(len(self.bot.guilds)), inline=True)
        embed.set_footer(text="Status is measured from the Discord gateway.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))
