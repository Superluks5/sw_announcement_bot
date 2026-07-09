"""
/announce command
------------------
Opens a popup form (draft, announcement number, name, rank),
polishes the draft with Groq's free AI API, fills in the template,
and posts the result to the channel.
"""

import os
import time
from datetime import datetime
import discord
from discord import app_commands
from discord.ext import commands
from groq import Groq

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
SERVER_NAME = os.environ.get("SERVER_NAME", "Your Server Name")
MODEL = "llama-3.3-70b-versatile"

groq_client = Groq(api_key=GROQ_API_KEY)

TEMPLATE = """🌌 「 SERVER ANNOUNCEMENT 」 🌌
━━━━━━━━━━━━━━━━━━━━━━━━━━

## 📢 {title}

{body}

━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 **Reference:**
> 🔹 **Announcement No.:** {ann_number}
> 🔹 **Date & Time:** <t:{timestamp}:F>

━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ *Please make sure to follow the server rules regarding this update.*

━━━━━━━━━━━━━━━━━━━━━━━━━━
**Signed,**
👤 **{user_name}**
🎖️ **Rank:** {rank}
— **Supreme Command**
🛰️ {server_name}"""


def polish_text(draft: str) -> tuple[str, str]:
    prompt = f"""You are helping write a professional Discord server announcement
for a Star Wars themed Roblox game community. Take the rough draft below and:

1. Write a short, clear title (no more than 6 words, no emojis, no quotes around it)
2. Rewrite the body in clear, professional, concise language. Keep it friendly
   but not overly casual. Do not add a greeting like "Hello everyone". Do not
   add a signature or sign-off. Do not use markdown headers.

Rough draft:
\"\"\"
{draft}
\"\"\"

Respond ONLY in this exact format, nothing else:
TITLE: <title here>
BODY: <body here>"""

    response = groq_client.chat.completions.create(
        model=MODEL,
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.choices[0].message.content

    if "TITLE:" in text and "BODY:" in text:
        title_part, body_part = text.split("BODY:", 1)
        title = title_part.replace("TITLE:", "").strip()
        body = body_part.strip()
    else:
        title = "Announcement"
        body = text.strip()

    return title, body


class AnnounceModal(discord.ui.Modal, title="New Announcement"):
    def __init__(self, ping_mention: str = ""):
        super().__init__()
        self.ping_mention = ping_mention

    draft = discord.ui.TextInput(
        label="Rough draft",
        style=discord.TextStyle.paragraph,
        placeholder="e.g. server update, new planets added, maintenance friday 6pm",
        required=True,
        max_length=1500,
    )
    ann_number = discord.ui.TextInput(
        label="Announcement number",
        placeholder="e.g. 1 (this becomes SC-2026-001 automatically)",
        required=True,
        max_length=10,
    )
    user_name = discord.ui.TextInput(
        label="Your name / username",
        required=True,
        max_length=50,
    )
    rank = discord.ui.TextInput(
        label="Your rank",
        required=True,
        max_length=50,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)

        try:
            title, body = polish_text(self.draft.value)
        except Exception as e:
            await interaction.followup.send(
                f"❌ Failed to reach the AI service: {e}", ephemeral=True
            )
            return

        timestamp = int(time.time())
        current_year = datetime.now().year

        # Build the number part (pad to 3 digits if it's a plain number, e.g. "1" -> "001")
        raw_number = self.ann_number.value.strip()
        if raw_number.isdigit():
            number_part = raw_number.zfill(3)
        else:
            number_part = raw_number  # fallback if they type something non-numeric

        full_ann_number = f"SC-{current_year}-{number_part}"

        final_message = TEMPLATE.format(
            title=title,
            body=body,
            ann_number=full_ann_number,
            timestamp=timestamp,
            user_name=self.user_name.value,
            rank=self.rank.value,
            server_name=SERVER_NAME,
        )

        # Prepend the ping (e.g. @everyone, @here, or a role mention) above the template
        message_to_post = f"{self.ping_mention}\n{final_message}" if self.ping_mention else final_message

        view = ConfirmView(message_to_post)
        preview_text = final_message if not self.ping_mention else f"{self.ping_mention} (ping shown as text in this preview)\n\n{final_message}"
        await interaction.followup.send(
            f"**Preview:**\n\n{preview_text}",
            view=view,
            ephemeral=True,
        )


class ConfirmView(discord.ui.View):
    def __init__(self, message: str):
        super().__init__(timeout=300)
        self.message = message

    @discord.ui.button(label="Post to channel", style=discord.ButtonStyle.green, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.channel.send(
            self.message,
            allowed_mentions=discord.AllowedMentions(everyone=True, roles=True, users=True),
        )
        await interaction.response.edit_message(content="✅ Posted!", view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="❌ Cancelled. Nothing was posted.", view=None)


class Announce(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="scannounce", description="Create and post a formatted server announcement")
    @app_commands.describe(
        ping="Who should be pinged with this announcement",
        role="Only needed if you picked 'Specific role' above",
    )
    @app_commands.choices(
        ping=[
            app_commands.Choice(name="No ping", value="none"),
            app_commands.Choice(name="@everyone", value="everyone"),
            app_commands.Choice(name="@here", value="here"),
            app_commands.Choice(name="Specific role", value="role"),
        ]
    )
    async def announce(
        self,
        interaction: discord.Interaction,
        ping: app_commands.Choice[str] = None,
        role: discord.Role = None,
    ):
        ping_value = ping.value if ping else "none"

        if ping_value == "everyone":
            ping_mention = "@everyone"
        elif ping_value == "here":
            ping_mention = "@here"
        elif ping_value == "role":
            if role is None:
                await interaction.response.send_message(
                    "⚠️ You picked 'Specific role' but didn't select a role. "
                    "Run the command again and fill in the `role` option.",
                    ephemeral=True,
                )
                return
            ping_mention = role.mention
        else:
            ping_mention = ""

        await interaction.response.send_modal(AnnounceModal(ping_mention=ping_mention))


async def setup(bot: commands.Bot):
    await bot.add_cog(Announce(bot))
