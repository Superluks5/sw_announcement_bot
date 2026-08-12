"""
/promote command + /rank link group
------------------
Promotes a member to a new rank role. If that rank role has "linked"
companion roles configured (e.g. promoting to Officer on Trial should also
add the Officer Corps separator role), those get added automatically too.

Set up links with:
  /rank link <rank_role> <companion_role>   - link a companion role
  /rank unlink <rank_role> <companion_role> - remove a link
  /rank links                                - view all current links

Then:
  /promote <member> <new_rank> [old_rank]   - promotes, auto-adds linked
                                               roles, optionally removes old_rank

Who can use these commands is controlled centrally in /permissions.py, not here.
"""

import os
import json
import discord
from discord import app_commands
from discord.ext import commands

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "rank_links_data.json")


def load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        return {"links": {}}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("links", {})
    return data


def save_data(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


class Promote(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    rank_group = app_commands.Group(name="rank", description="Configure linked roles used by /promote")

    # ---------- /rank link / unlink / links ----------

    @rank_group.command(name="link", description="Link a companion role to a rank role")
    @app_commands.describe(
        rank_role="The rank role (e.g. Officer on Trial)",
        companion_role="The role to auto-add whenever someone is promoted to rank_role (e.g. Officer Corps)",
    )
    async def link(self, interaction: discord.Interaction, rank_role: discord.Role, companion_role: discord.Role):
        data = load_data()
        key = str(rank_role.id)
        companions = data["links"].setdefault(key, [])
        if companion_role.id in companions:
            await interaction.response.send_message(
                f"ℹ️ {companion_role.mention} is already linked to {rank_role.mention}.", ephemeral=True
            )
            return

        companions.append(companion_role.id)
        save_data(data)
        await interaction.response.send_message(
            f"🔗 Linked: promoting to {rank_role.mention} will now also add {companion_role.mention}.",
            ephemeral=True,
        )

    @rank_group.command(name="unlink", description="Remove a linked companion role")
    @app_commands.describe(rank_role="The rank role", companion_role="The companion role to unlink")
    async def unlink(self, interaction: discord.Interaction, rank_role: discord.Role, companion_role: discord.Role):
        data = load_data()
        key = str(rank_role.id)
        companions = data["links"].get(key, [])
        if companion_role.id not in companions:
            await interaction.response.send_message(
                f"⚠️ {companion_role.mention} isn't linked to {rank_role.mention}.", ephemeral=True
            )
            return

        companions.remove(companion_role.id)
        if not companions:
            data["links"].pop(key, None)
        save_data(data)
        await interaction.response.send_message(
            f"🔗 Unlinked {companion_role.mention} from {rank_role.mention}.", ephemeral=True
        )

    @rank_group.command(name="links", description="View all configured rank -> companion role links")
    async def links(self, interaction: discord.Interaction):
        data = load_data()
        if not data["links"]:
            await interaction.response.send_message("*No rank links configured yet.*", ephemeral=True)
            return

        lines = []
        for rank_id, companion_ids in data["links"].items():
            companions_text = ", ".join(f"<@&{c}>" for c in companion_ids)
            lines.append(f"<@&{rank_id}> → {companions_text}")

        embed = discord.Embed(
            title="🔗 Rank → Companion Role Links",
            description="\n".join(lines),
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ---------- /promote ----------

    @app_commands.command(name="promote", description="Promote a member to a new rank")
    @app_commands.describe(
        member="Who to promote",
        new_rank="The new rank role to give them",
        old_rank="Optional - a previous rank role to remove at the same time",
        announce="Post a promotion announcement in this channel? Defaults to yes.",
    )
    async def promote(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        new_rank: discord.Role,
        old_rank: discord.Role = None,
        announce: bool = True,
    ):
        await interaction.response.defer(ephemeral=True)

        data = load_data()
        companion_ids = data["links"].get(str(new_rank.id), [])
        companion_roles = [interaction.guild.get_role(rid) for rid in companion_ids]
        companion_roles = [r for r in companion_roles if r is not None]

        roles_to_add = [new_rank] + companion_roles
        added, failed = [], []

        for role in roles_to_add:
            try:
                await member.add_roles(role, reason=f"Promoted by {interaction.user}")
                added.append(role)
            except discord.Forbidden:
                failed.append(role)

        removed_note = ""
        if old_rank is not None:
            try:
                await member.remove_roles(old_rank, reason=f"Promoted by {interaction.user}")
                removed_note = f" and removed {old_rank.mention}"
            except discord.Forbidden:
                removed_note = f" (⚠️ couldn't remove {old_rank.mention} - check the bot's role position)"

        summary = f"✅ {member.mention} promoted to {new_rank.mention}"
        if len(added) > 1:
            extra = ", ".join(r.mention for r in added[1:])
            summary += f" (also added: {extra})"
        summary += removed_note
        if failed:
            failed_text = ", ".join(r.mention for r in failed)
            summary += f"\n⚠️ Couldn't add: {failed_text} - check the bot's role is positioned above them."

        await interaction.followup.send(summary, ephemeral=True)

        if announce:
            embed = discord.Embed(
                title="📈 Promotion Notice",
                description=f"{member.mention} has been promoted to {new_rank.mention}!",
                color=discord.Color.gold(),
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            await interaction.channel.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Promote(bot))