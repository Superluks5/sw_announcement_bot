"""
/taskboard command group
------------------------
A shared taskboard where each dev gets their own section (To Do / In
Progress / Done). Posts as a "live" message that auto-updates - same
pattern as /roadmap, /team, /blocker, /testflight.

Subcommands:
  /taskboard add      - add a task assigned to a dev
  /taskboard update   - change a task's status
  /taskboard remove   - remove a task
  /taskboard mytasks  - quick private view of just your own tasks
  /taskboard show     - post (or move) the live board to this channel
  /taskboard clear    - wipe all tasks (optionally just for one dev)
"""

import os
import json
import discord
from discord import app_commands
from discord.ext import commands

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "taskboard_data.json")

STATUS_CHOICES = [
    app_commands.Choice(name="⬜ To Do", value="todo"),
    app_commands.Choice(name="🟦 In Progress", value="in_progress"),
    app_commands.Choice(name="✅ Done", value="done"),
]
STATUS_LABELS = {"todo": "⬜ To Do", "in_progress": "🟦 In Progress", "done": "✅ Done"}
STATUS_ORDER = {"in_progress": 0, "todo": 1, "done": 2}


def load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        return {"tasks": [], "channel_id": None, "message_id": None}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("tasks", [])
    data.setdefault("channel_id", None)
    data.setdefault("message_id", None)
    return data


def save_data(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def build_taskboard_embed(data: dict) -> discord.Embed:
    embed = discord.Embed(title="📋 Dev Taskboard", color=discord.Color.blurple())

    tasks = data["tasks"]
    if not tasks:
        embed.description = "*No tasks on the board yet.*"
        embed.set_footer(text="Updates automatically when tasks are added or changed.")
        return embed

    by_assignee = {}
    for t in tasks:
        by_assignee.setdefault(t["assignee_id"], []).append(t)

    for assignee_id, assignee_tasks in by_assignee.items():
        ordered = sorted(assignee_tasks, key=lambda t: STATUS_ORDER.get(t["status"], 99))
        lines = [f"<@{assignee_id}>"]
        for i, t in enumerate(ordered):
            lines.append(f"`{i+1}.` {STATUS_LABELS[t['status']]} — {t['text']}")
        embed.add_field(name="👤 Assignee", value="\n".join(lines), inline=False)

    embed.set_footer(text="Updates automatically when tasks are added or changed.")
    return embed


def find_task(data: dict, assignee_id: int, number: int):
    """Get the Nth task for a specific assignee, in the same order shown in the embed."""
    assignee_tasks = [t for t in data["tasks"] if t["assignee_id"] == assignee_id]
    ordered = sorted(assignee_tasks, key=lambda t: STATUS_ORDER.get(t["status"], 99))
    if number < 1 or number > len(ordered):
        return None
    return ordered[number - 1]


class Taskboard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    taskboard_group = app_commands.Group(name="taskboard", description="Shared taskboard, grouped per dev")

    async def refresh_live_message(self, data: dict):
        channel_id = data.get("channel_id")
        message_id = data.get("message_id")
        if not channel_id or not message_id:
            return False

        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except discord.HTTPException:
                return False

        try:
            message = await channel.fetch_message(message_id)
        except discord.HTTPException:
            return False

        await message.edit(embed=build_taskboard_embed(data))
        return True

    @taskboard_group.command(name="add", description="Add a task assigned to a dev")
    @app_commands.describe(assignee="Who's responsible for this task", task="What needs to be done")
    async def add(self, interaction: discord.Interaction, assignee: discord.Member, task: str):
        data = load_data()
        data["tasks"].append({"assignee_id": assignee.id, "text": task, "status": "todo"})
        save_data(data)
        updated_live = await self.refresh_live_message(data)
        note = "" if updated_live else "\n*(No live taskboard message set yet - use `/taskboard show` in a channel first.)*"
        await interaction.response.send_message(
            f"✅ Added task for {assignee.mention}: {task}{note}", ephemeral=True
        )

    @taskboard_group.command(name="update", description="Change a task's status")
    @app_commands.describe(
        assignee="Whose task list this is",
        number="Task number for that person (see /taskboard show)",
        status="New status",
    )
    @app_commands.choices(status=STATUS_CHOICES)
    async def update(
        self,
        interaction: discord.Interaction,
        assignee: discord.Member,
        number: int,
        status: app_commands.Choice[str],
    ):
        data = load_data()
        task = find_task(data, assignee.id, number)

        if not task:
            await interaction.response.send_message(
                f"⚠️ There's no task #{number} for {assignee.mention}. Use `/taskboard show` to check numbers.",
                ephemeral=True,
            )
            return

        task["status"] = status.value
        save_data(data)
        updated_live = await self.refresh_live_message(data)
        note = "" if updated_live else "\n*(No live taskboard message set yet - use `/taskboard show` in a channel first.)*"
        await interaction.response.send_message(
            f"✅ Updated {assignee.mention}'s task to {STATUS_LABELS[status.value]}: {task['text']}{note}",
            ephemeral=True,
        )

    @taskboard_group.command(name="remove", description="Remove a task")
    @app_commands.describe(assignee="Whose task list this is", number="Task number for that person (see /taskboard show)")
    async def remove(self, interaction: discord.Interaction, assignee: discord.Member, number: int):
        data = load_data()
        task = find_task(data, assignee.id, number)

        if not task:
            await interaction.response.send_message(
                f"⚠️ There's no task #{number} for {assignee.mention}. Use `/taskboard show` to check numbers.",
                ephemeral=True,
            )
            return

        data["tasks"].remove(task)
        save_data(data)
        updated_live = await self.refresh_live_message(data)
        note = "" if updated_live else "\n*(No live taskboard message set yet - use `/taskboard show` in a channel first.)*"
        await interaction.response.send_message(f"🗑️ Removed: {task['text']}{note}", ephemeral=True)

    @taskboard_group.command(name="mytasks", description="See just your own tasks")
    async def mytasks(self, interaction: discord.Interaction):
        data = load_data()
        my_tasks = [t for t in data["tasks"] if t["assignee_id"] == interaction.user.id]

        if not my_tasks:
            await interaction.response.send_message("You have no tasks on the board.", ephemeral=True)
            return

        ordered = sorted(my_tasks, key=lambda t: STATUS_ORDER.get(t["status"], 99))
        lines = [f"`{i+1}.` {STATUS_LABELS[t['status']]} — {t['text']}" for i, t in enumerate(ordered)]

        embed = discord.Embed(title="📋 Your Tasks", description="\n".join(lines), color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @taskboard_group.command(name="clear", description="Clear all tasks (optionally just for one dev)")
    @app_commands.describe(assignee="Optional - only clear this person's tasks. Leave blank to clear the whole board.")
    async def clear(self, interaction: discord.Interaction, assignee: discord.Member = None):
        data = load_data()
        if assignee:
            data["tasks"] = [t for t in data["tasks"] if t["assignee_id"] != assignee.id]
            label = assignee.display_name
        else:
            data["tasks"] = []
            label = "the whole board"

        save_data(data)
        updated_live = await self.refresh_live_message(data)
        note = "" if updated_live else "\n*(No live taskboard message set yet - use `/taskboard show` in a channel first.)*"
        await interaction.response.send_message(f"🧹 Cleared tasks for {label}.{note}", ephemeral=True)

    @taskboard_group.command(name="show", description="Post (or move) the live taskboard to this channel")
    async def show(self, interaction: discord.Interaction):
        data = load_data()
        embed = build_taskboard_embed(data)
        await interaction.response.send_message(embed=embed)
        sent_message = await interaction.original_response()

        data["channel_id"] = interaction.channel_id
        data["message_id"] = sent_message.id
        save_data(data)


async def setup(bot: commands.Bot):
    await bot.add_cog(Taskboard(bot))