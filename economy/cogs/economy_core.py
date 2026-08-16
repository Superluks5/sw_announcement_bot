"""
Economy core commands - Phase 1.
------------------------------------------
/balance, /pay, /deposit, /withdraw. Admin commands (/economy give/remove/
set/reset) come in Phase 2 once the permission engine exists - these four
are safe to ship now since they only ever act on the calling user's own
money (or, for /pay, move money the sender explicitly chose to give away).
"""

import discord
from discord import app_commands
from discord.ext import commands

from economy.services import balance_service as bs
from economy.exceptions import EconomyError


def format_money(amount: int, symbol: str) -> str:
    return f"{symbol}{amount:,}"


class EconomyCore(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="balance", description="Check your (or someone else's) balance")
    @app_commands.describe(member="Optional - whose balance to check. Defaults to you.")
    async def balance(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        settings = bs.get_guild_settings(interaction.guild_id)
        bal = bs.get_balance(interaction.guild_id, target.id)

        embed = discord.Embed(title=f"💰 {target.display_name}'s Balance", color=discord.Color.gold())
        embed.add_field(name="Cash", value=format_money(bal["cash"], settings.currency_symbol), inline=True)
        embed.add_field(name="Bank", value=format_money(bal["bank"], settings.currency_symbol), inline=True)
        embed.add_field(name="Net Worth", value=format_money(bal["net_worth"], settings.currency_symbol), inline=True)
        embed.set_thumbnail(url=target.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="pay", description="Send money to another member")
    @app_commands.describe(member="Who to pay", amount="How much to send", reason="Optional note")
    async def pay(self, interaction: discord.Interaction, member: discord.Member, amount: int, reason: str = None):
        if member.bot:
            await interaction.response.send_message("You can't pay a bot.", ephemeral=True)
            return

        settings = bs.get_guild_settings(interaction.guild_id)
        try:
            result = bs.transfer(interaction.guild_id, interaction.user.id, member.id, amount, reason=reason)
        except EconomyError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            return

        embed = discord.Embed(
            description=f"{interaction.user.mention} paid {member.mention} **{format_money(amount, settings.currency_symbol)}**"
            + (f"\n*{reason}*" if reason else ""),
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="deposit", description="Move cash into your bank")
    @app_commands.describe(amount="How much to deposit")
    async def deposit(self, interaction: discord.Interaction, amount: int):
        settings = bs.get_guild_settings(interaction.guild_id)
        try:
            result = bs.deposit(interaction.guild_id, interaction.user.id, amount)
        except EconomyError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            return
        await interaction.response.send_message(
            f"🏦 Deposited **{format_money(amount, settings.currency_symbol)}**. "
            f"Cash: {format_money(result['cash'], settings.currency_symbol)} | "
            f"Bank: {format_money(result['bank'], settings.currency_symbol)}"
        )

    @app_commands.command(name="withdraw", description="Move money from your bank to cash")
    @app_commands.describe(amount="How much to withdraw")
    async def withdraw(self, interaction: discord.Interaction, amount: int):
        settings = bs.get_guild_settings(interaction.guild_id)
        try:
            result = bs.withdraw(interaction.guild_id, interaction.user.id, amount)
        except EconomyError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            return
        await interaction.response.send_message(
            f"💵 Withdrew **{format_money(amount, settings.currency_symbol)}**. "
            f"Cash: {format_money(result['cash'], settings.currency_symbol)} | "
            f"Bank: {format_money(result['bank'], settings.currency_symbol)}"
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(EconomyCore(bot))
