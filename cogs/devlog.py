"""
/devlog command
------------------
A plain formatting command (no AI) for development update / changelog posts.
Opens a form with Added / Fixed / Removed sections and formats them into
a clean patch-notes style layout, similar to a typical changelog channel.
"""

import os
import time
import discord
from discord import app_commands
from discord.ext import commands

SERVER_NAME = os.environ.get("SERVER_NAME", "Your Server Name")


def format_lines(raw_text: str, prefix: str) -> str:
    """Take multi-line text and prefix each non-empty line, e.g. '[+] '."""
    if not raw_text.strip():
        return ""
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    return "\n".join(f"{prefix} {line}" for line in lines)


def build_devlog_message(version_title, added, fixed, removed, author_name, timestamp):
    sections = []
    added_fmt = format_lines(added, "[+]")
    fixed_fmt = format_lines(fixed, "[0]")
    removed_fmt = format_lines(removed, "[-]")

    if added_fmt:
        sections.append(added_fmt)
    if fixed_fmt:
        sections.append(fixed_fmt)
    if removed_fmt:
        sections.append(removed_fmt)

    code_block = "\n\n".join(sections) if sections else "No changes listed."

    message = f"""🔧 「 DEVELOPMENT UPDATE 」 🔧
━━━━━━━━━━━━━━━━━━━━━━━━━━

## {version_title}

```
{code_block}
```

**Legend:** `[+]` Added &nbsp; `[0]` Fixed/Edited &nbsp; `[-]` Removed

━━━━━━━━━━━━━━━━━━━━━━━━━━
🕒 <t:{timestamp}:F>
— **{author_name}**
🛰️ {server_name}""".replace("&nbsp;", " ").replace("{server_name}", SERVER_NAME)

    return message


class DevlogModal(discord.ui.Modal, title="New Development Update"):
    version_title = discord.ui.TextInput(
        label="Update title",
        placeholder="e.g. v1.4 Update, Weekly Patch #12",
        required=True,
        max_length=100,
    )
    added = discord.ui.TextInput(
        label="Added (one per line)",
        style=discord.TextStyle.paragraph,
        placeholder="New planet: Hoth\nNew blaster skin",
        required=False,
        max_length=800,
    )
    fixed = discord.ui.TextInput(
        label="Fixed / Edited (one per line)",
        style=discord.TextStyle.paragraph,
        placeholder="Fixed lightsaber clipping bug",
        required=False,
        max_length=800,
    )
    removed = discord.ui.TextInput(
        label="Removed (one per line)",
        style=discord.TextStyle.paragraph,
        placeholder="Removed old spawn point",
        required=False,
        max_length=800,
    )
    author_name = discord.ui.TextInput(
        label="Your name",
        required=True,
        max_length=50,
    )

    async def on_submit(self, interaction: discord.Interaction):
        timestamp = int(time.time())
        message = build_devlog_message(
            version_title=self.version_title.value,
            added=self.added.value,
            fixed=self.fixed.value,
            removed=self.removed.value,
            author_name=self.author_name.value,
            timestamp=timestamp,
        )

        view = DevlogConfirmView(message)
        await interaction.response.send_message(
            f"**Preview:**\n\n{message}",
            view=view,
            ephemeral=True,
        )


class DevlogConfirmView(discord.ui.View):
    def __init__(self, message: str):
        super().__init__(timeout=300)
        self.message = message

    @discord.ui.button(label="Post to channel", style=discord.ButtonStyle.green, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.channel.send(self.message)
        await interaction.response.edit_message(content="✅ Posted!", view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="❌ Cancelled. Nothing was posted.", view=None)


class Devlog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="devlog", description="Post a development update / changelog")
    async def devlog(self, interaction: discord.Interaction):
        await interaction.response.send_modal(DevlogModal())


async def setup(bot: commands.Bot):
    await bot.add_cog(Devlog(bot))