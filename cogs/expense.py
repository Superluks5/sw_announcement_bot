"""
/expense command group
------------------------
Track shared expenses between co-owners/devs (e.g. paying for a game pass,
Roblox premium, ads) and see who owes who. Splits each expense evenly among
whoever's listed as a participant. Data saved locally in JSON.

Subcommands:
  /expense add    - log an expense, split between the payer and other participants
  /expense show   - see each person's net balance (positive = owed to them, negative = they owe)
  /expense remove - remove a logged expense by its number
  /expense clear  - wipe the whole ledger
"""

import os
import json
from datetime import date
import discord
from discord import app_commands
from discord.ext import commands

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "expense_data.json")


def load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        return {"expenses": []}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("expenses", [])
    return data


def save_data(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


class Expense(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    expense_group = app_commands.Group(name="expense", description="Track and split shared expenses")

    @expense_group.command(name="add", description="Log an expense split between the payer and other participants")
    @app_commands.describe(
        amount="Total amount paid",
        description="What was it for, e.g. 'Roblox Premium - July'",
        payer="Who paid for it",
        participant2="Optional - another person splitting this cost",
        participant3="Optional - another person splitting this cost",
        participant4="Optional - another person splitting this cost",
    )
    async def add(
        self,
        interaction: discord.Interaction,
        amount: float,
        description: str,
        payer: discord.Member,
        participant2: discord.Member = None,
        participant3: discord.Member = None,
        participant4: discord.Member = None,
    ):
        participants = [payer]
        for p in (participant2, participant3, participant4):
            if p is not None and p.id not in [x.id for x in participants]:
                participants.append(p)

        share = amount / len(participants)

        data = load_data()
        data["expenses"].append({
            "amount": amount,
            "description": description,
            "payer_id": payer.id,
            "payer_name": payer.display_name,
            "participant_ids": [p.id for p in participants],
            "participant_names": [p.display_name for p in participants],
            "date": date.today().isoformat(),
        })
        save_data(data)

        others = [p.display_name for p in participants if p.id != payer.id]
        others_text = ", ".join(others) if others else "no one else (fully covered by payer)"

        await interaction.response.send_message(
            f"✅ Logged **{amount:,.2f}** for *{description}*, paid by **{payer.display_name}**.\n"
            f"Split {len(participants)} ways ({share:,.2f} each). Owing: {others_text}",
        )

    @expense_group.command(name="show", description="See everyone's net balance from logged expenses")
    async def show(self, interaction: discord.Interaction):
        data = load_data()
        expenses = data["expenses"]

        if not expenses:
            await interaction.response.send_message("No expenses logged yet.", ephemeral=True)
            return

        balances = {}  # user_id -> {"name": str, "net": float}

        for e in expenses:
            participant_ids = e["participant_ids"]
            participant_names = e["participant_names"]
            share = e["amount"] / len(participant_ids)

            for pid, pname in zip(participant_ids, participant_names):
                balances.setdefault(pid, {"name": pname, "net": 0.0})
                if pid == e["payer_id"]:
                    # payer is owed by everyone else's share
                    balances[pid]["net"] += e["amount"] - share
                else:
                    balances[pid]["net"] -= share

        lines = []
        for pid, info in sorted(balances.items(), key=lambda x: -x[1]["net"]):
            net = info["net"]
            if net > 0.01:
                lines.append(f"🟢 **{info['name']}** is owed **{net:,.2f}**")
            elif net < -0.01:
                lines.append(f"🔴 **{info['name']}** owes **{abs(net):,.2f}**")
            else:
                lines.append(f"⚪ **{info['name']}** is settled up")

        embed = discord.Embed(
            title="💸 Expense Balances",
            description="\n".join(lines),
            color=discord.Color.orange(),
        )
        embed.set_footer(text=f"{len(expenses)} expenses logged")
        await interaction.response.send_message(embed=embed)

    @expense_group.command(name="remove", description="Remove a logged expense by its number (most recent = 1)")
    @app_commands.describe(number="Entry number, counting from the most recent (1 = latest)")
    async def remove(self, interaction: discord.Interaction, number: int):
        data = load_data()
        expenses = data["expenses"]
        recent_first = list(reversed(expenses))

        if number < 1 or number > len(recent_first):
            await interaction.response.send_message(
                f"⚠️ There's no entry #{number}. There are {len(expenses)} expenses logged.", ephemeral=True
            )
            return

        target = recent_first[number - 1]
        expenses.remove(target)
        save_data(data)
        await interaction.response.send_message(
            f"🗑️ Removed: {target['amount']:,.2f} for {target['description']} ({target['date']})",
            ephemeral=True,
        )

    @expense_group.command(name="clear", description="Wipe the entire expense ledger")
    async def clear(self, interaction: discord.Interaction):
        save_data({"expenses": []})
        await interaction.response.send_message("🧹 Expense ledger cleared.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Expense(bot))
