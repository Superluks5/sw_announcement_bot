"""
Economy admin commands - Phase 2.
------------------------------------------
/economy give/remove/set/reset/reset-server. Every single one goes through
permission_service.is_allowed_for_interaction() FIRST - never Discord's
own Administrator/Manage Server permission. Every successful action writes
an AuditLog row in addition to the Transaction row balance_service already
writes.
"""

import discord
from discord import app_commands
from discord.ext import commands

from economy.services import balance_service as bs
from economy.services import permission_service as ps
from economy.exceptions import EconomyError


def format_money(amount: int, symbol: str) -> str:
    return f"{symbol}{amount:,}"


async def _check_or_deny(interaction: discord.Interaction, command: str) -> bool:
    result = ps.is_allowed_for_interaction(interaction, command)
    if not result.allowed:
        await interaction.response.send_message(
            f"🚫 You don't have the required economy permission for `/{command}`.\n"
            f"-# {result.reason}",
            ephemeral=True,
        )
    return result.allowed


class EconomyAdmin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    economy_group = app_commands.Group(name="economy", description="Economy administration (requires an economy permission grant)")

    @economy_group.command(name="give", description="Add money to a member's balance")
    @app_commands.describe(member="Who to give money to", amount="How much", reason="Why (shown in audit log)")
    async def give(self, interaction: discord.Interaction, member: discord.Member, amount: int, reason: str = None):
        if not await _check_or_deny(interaction, "economy give"):
            return
        settings = bs.get_guild_settings(interaction.guild_id)
        try:
            result = bs.add_cash(
                interaction.guild_id, member.id, amount, reason=reason, command="economy give",
                performed_by=interaction.user.id, txn_type="admin_give",
            )
        except EconomyError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            return

        ps.record_audit(
            interaction.guild_id, interaction.user.id, "economy_give", member.id,
            f"Gave {format_money(amount, settings.currency_symbol)} to {member}" + (f" - {reason}" if reason else ""),
        )
        embed = discord.Embed(
            title="💰 Economy Action: Give",
            color=discord.Color.green(),
            description=f"Gave **{format_money(amount, settings.currency_symbol)}** to {member.mention}",
        )
        embed.add_field(name="New Balance", value=format_money(result["cash"], settings.currency_symbol))
        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_footer(text=f"By {interaction.user}")
        await interaction.response.send_message(embed=embed)

    @economy_group.command(name="remove", description="Remove money from a member's balance")
    @app_commands.describe(member="Who to remove money from", amount="How much", reason="Why (shown in audit log)")
    async def remove(self, interaction: discord.Interaction, member: discord.Member, amount: int, reason: str = None):
        if not await _check_or_deny(interaction, "economy remove"):
            return
        settings = bs.get_guild_settings(interaction.guild_id)
        try:
            result = bs.remove_cash(
                interaction.guild_id, member.id, amount, reason=reason, command="economy remove",
                performed_by=interaction.user.id, txn_type="admin_remove",
            )
        except EconomyError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            return

        ps.record_audit(
            interaction.guild_id, interaction.user.id, "economy_remove", member.id,
            f"Removed {format_money(amount, settings.currency_symbol)} from {member}" + (f" - {reason}" if reason else ""),
        )
        embed = discord.Embed(
            title="💸 Economy Action: Remove",
            color=discord.Color.orange(),
            description=f"Removed **{format_money(amount, settings.currency_symbol)}** from {member.mention}",
        )
        embed.add_field(name="New Balance", value=format_money(result["cash"], settings.currency_symbol))
        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_footer(text=f"By {interaction.user}")
        await interaction.response.send_message(embed=embed)

    @economy_group.command(name="set", description="Set a member's cash balance to an exact amount")
    @app_commands.describe(member="Whose balance to set", amount="The exact new balance", reason="Why (shown in audit log)")
    async def set_balance(self, interaction: discord.Interaction, member: discord.Member, amount: int, reason: str = None):
        if not await _check_or_deny(interaction, "economy set"):
            return
        settings = bs.get_guild_settings(interaction.guild_id)
        try:
            result = bs.set_cash(
                interaction.guild_id, member.id, amount, reason=reason, command="economy set",
                performed_by=interaction.user.id,
            )
        except EconomyError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            return

        ps.record_audit(
            interaction.guild_id, interaction.user.id, "economy_set", member.id,
            f"Set {member}'s balance to {format_money(amount, settings.currency_symbol)}" + (f" - {reason}" if reason else ""),
        )
        embed = discord.Embed(
            title="⚙️ Economy Action: Set",
            color=discord.Color.blue(),
            description=f"Set {member.mention}'s balance to **{format_money(amount, settings.currency_symbol)}**",
        )
        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_footer(text=f"By {interaction.user}")
        await interaction.response.send_message(embed=embed)

    @economy_group.command(name="reset", description="Reset a member's balance to zero")
    @app_commands.describe(member="Whose balance to reset", reason="Why (shown in audit log)")
    async def reset(self, interaction: discord.Interaction, member: discord.Member, reason: str = None):
        if not await _check_or_deny(interaction, "economy reset"):
            return
        ps.record_audit(interaction.guild_id, interaction.user.id, "economy_reset", member.id, reason)
        bs.reset_balance(interaction.guild_id, member.id, performed_by=interaction.user.id, reason=reason)
        embed = discord.Embed(
            title="🔄 Economy Action: Reset",
            color=discord.Color.red(),
            description=f"Reset {member.mention}'s balance to zero.",
        )
        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_footer(text=f"By {interaction.user}")
        await interaction.response.send_message(embed=embed)

    @economy_group.command(name="reset-server", description="DANGER: reset EVERY member's balance on this server")
    @app_commands.describe(confirm="Type exactly: CONFIRM")
    async def reset_server(self, interaction: discord.Interaction, confirm: str):
        if not await _check_or_deny(interaction, "economy reset-server"):
            return
        if confirm != "CONFIRM":
            await interaction.response.send_message(
                "⚠️ This resets **every balance on the server**. Re-run with `confirm: CONFIRM` (exact text) to proceed.",
                ephemeral=True,
            )
            return

        from economy.db import SessionLocal
        from economy.models import Balance
        with SessionLocal() as session:
            count = session.query(Balance).filter_by(guild_id=interaction.guild_id).update({"cash": 0, "bank": 0})
            session.commit()

        ps.record_audit(interaction.guild_id, interaction.user.id, "economy_reset_server", None, f"Reset {count} balances")
        await interaction.response.send_message(f"🔄 Reset **{count}** member balances to zero.")


async def setup(bot: commands.Bot):
    await bot.add_cog(EconomyAdmin(bot))
