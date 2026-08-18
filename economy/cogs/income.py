"""
Income commands - Phase 4.
------------------------------------------
/work /crime /rob /daily /weekly, plus a background task that grants
configured role income (e.g. @VIP -> 500 every 12h) automatically.
"""

import discord
from discord import app_commands
from discord.ext import commands, tasks

from economy.services import balance_service as bs
from economy.services import income_service as inc
from economy.db import SessionLocal
from economy.models import RoleIncome
from economy.exceptions import EconomyError


def format_money(amount: int, symbol: str) -> str:
    return f"{symbol}{amount:,}"


class Income(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.grant_role_income.start()

    def cog_unload(self):
        self.grant_role_income.cancel()

    @app_commands.command(name="work", description="Work a shift for some money")
    async def work(self, interaction: discord.Interaction):
        settings = bs.get_guild_settings(interaction.guild_id)
        try:
            result = inc.do_work(interaction.guild_id, interaction.user.id)
        except EconomyError as e:
            await interaction.response.send_message(f"⏳ {e}", ephemeral=True)
            return

        embed = discord.Embed(
            description=f"💼 You worked a shift and earned **{format_money(result.payout, settings.currency_symbol)}**.",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="crime", description="Attempt a crime for a bigger payout - risky")
    async def crime(self, interaction: discord.Interaction):
        settings = bs.get_guild_settings(interaction.guild_id)
        try:
            result = inc.do_crime(interaction.guild_id, interaction.user.id)
        except EconomyError as e:
            await interaction.response.send_message(f"⏳ {e}", ephemeral=True)
            return

        if result.success:
            embed = discord.Embed(
                description=f"🕵️ The heist paid off! You made **{format_money(result.amount, settings.currency_symbol)}**.",
                color=discord.Color.green(),
            )
        else:
            embed = discord.Embed(
                description=f"🚨 Caught red-handed! You paid a fine of **{format_money(result.amount, settings.currency_symbol)}**.",
                color=discord.Color.red(),
            )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="rob", description="Attempt to rob another member")
    @app_commands.describe(member="Who to rob")
    async def rob(self, interaction: discord.Interaction, member: discord.Member):
        if member.bot:
            await interaction.response.send_message("You can't rob a bot.", ephemeral=True)
            return

        settings = bs.get_guild_settings(interaction.guild_id)
        try:
            result = inc.do_rob(interaction.guild_id, interaction.user.id, member.id)
        except EconomyError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            return

        if result.success:
            embed = discord.Embed(
                description=f"💰 You robbed {member.mention} for **{format_money(result.amount, settings.currency_symbol)}**!",
                color=discord.Color.green(),
            )
        else:
            embed = discord.Embed(
                description=f"🚔 You got caught trying to rob {member.mention} and paid a **{format_money(result.amount, settings.currency_symbol)}** fine.",
                color=discord.Color.red(),
            )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="daily", description="Claim your daily reward")
    async def daily(self, interaction: discord.Interaction):
        settings = bs.get_guild_settings(interaction.guild_id)
        try:
            result = inc.do_daily(interaction.guild_id, interaction.user.id)
        except EconomyError as e:
            await interaction.response.send_message(f"⏳ {e}", ephemeral=True)
            return

        embed = discord.Embed(title="📅 Daily Reward", color=discord.Color.gold())
        embed.add_field(name="Reward", value=format_money(result.payout, settings.currency_symbol), inline=True)
        embed.add_field(name="Streak", value=f"🔥 {result.streak}" + (" (reset)" if result.streak_reset and result.streak == 1 else ""), inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="weekly", description="Claim your weekly reward")
    async def weekly(self, interaction: discord.Interaction):
        settings = bs.get_guild_settings(interaction.guild_id)
        try:
            result = inc.do_weekly(interaction.guild_id, interaction.user.id)
        except EconomyError as e:
            await interaction.response.send_message(f"⏳ {e}", ephemeral=True)
            return

        embed = discord.Embed(title="🗓️ Weekly Reward", color=discord.Color.gold())
        embed.add_field(name="Reward", value=format_money(result.payout, settings.currency_symbol), inline=True)
        embed.add_field(name="Streak", value=f"🔥 {result.streak}" + (" (reset)" if result.streak_reset and result.streak == 1 else ""), inline=True)
        await interaction.response.send_message(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        role_ids = [r.id for r in getattr(message.author, "roles", [])]
        inc.maybe_grant_chat_money(message.guild.id, message.author.id, message.channel.id, role_ids)

    # ---------- role income (automatic, background task) ----------

    @tasks.loop(minutes=30)
    async def grant_role_income(self):
        with SessionLocal() as session:
            rules = session.query(RoleIncome).filter_by(enabled=True).all()

        for rule in rules:
            guild = self.bot.get_guild(rule.guild_id)
            if guild is None:
                continue
            role = guild.get_role(rule.role_id)
            if role is None:
                continue

            cooldown_key = f"role_income_{rule.role_id}"
            for member in role.members:
                if member.bot:
                    continue
                remaining = bs.check_cooldown(rule.guild_id, member.id, cooldown_key)
                if remaining:
                    continue
                bs.set_cooldown(rule.guild_id, member.id, cooldown_key, rule.interval_hours * 3600)
                bs.add_cash(rule.guild_id, member.id, rule.amount, command="role_income", txn_type="income_role")

    @grant_role_income.before_loop
    async def before_role_income(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(Income(bot))