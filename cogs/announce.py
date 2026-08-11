"""
/announce command
------------------
Opens a popup form (draft, announcement number, name, rank), fills in
the template, and posts the result to the channel. AI polishing (via
Groq's free API) is on by default but can be turned off with the
`ai_polish` option - in that case you type the title and body exactly
as you want them posted, no rewriting.
"""

import os
import io
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
for a Star Wars themed Roblox game community taking place in the Imperial Timeline. (Roblox Game is in Development) Take the rough draft below and:

1. Write a short, clear title (no more than 6 words, no emojis, no quotes around it)
2. Rewrite the body in clear, professional, concise language. Keep it friendly
   but not overly casual. Do not add a greeting like "Hello everyone". Do not
   add a signature or sign-off. Do not use markdown headers. And do not add any emojis. It has to be suitable for a Discord announcement channel. And it has to be suitable for a Star Wars themed Roblox game community. Do not add any extra information that is not in the draft. Do not make up any new information. Keep it concise and to the point. It has to have same meaning as the draft. Do not add any extra information that is not in the draft. Do not make up any new information. Keep it concise and to the point. It has to have same meaning as the draft.

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


def build_message(title, body, ann_number, timestamp, user_name, rank, ping_mention):
    """Build the final formatted message and its preview text from all the pieces."""
    final_message = TEMPLATE.format(
        title=title,
        body=body,
        ann_number=ann_number,
        timestamp=timestamp,
        user_name=user_name,
        rank=rank,
        server_name=SERVER_NAME,
    )
    message_to_post = f"{ping_mention}\n{final_message}" if ping_mention else final_message
    preview_text = (
        final_message
        if not ping_mention
        else f"{ping_mention} (ping shown as text in this preview)\n\n{final_message}"
    )
    return message_to_post, preview_text


class AnnounceModal(discord.ui.Modal, title="New Announcement"):
    def __init__(self, ping_mention: str = "", image_bytes: bytes = None, image_filename: str = None, ai_polish: bool = True):
        super().__init__()
        self.ping_mention = ping_mention
        self.image_bytes = image_bytes
        self.image_filename = image_filename
        self.ai_polish = ai_polish

        # AI off -> you write the exact title yourself (5 fields total, Discord's modal max)
        if not ai_polish:
            self.title_input = discord.ui.TextInput(
                label="Title",
                placeholder="e.g. Server Maintenance Friday",
                required=True,
                max_length=100,
            )
            self.add_item(self.title_input)

        self.draft = discord.ui.TextInput(
            label="Rough draft" if ai_polish else "Body (posted exactly as typed)",
            style=discord.TextStyle.paragraph,
            placeholder=(
                "e.g. server update, new planets added, maintenance friday 6pm"
                if ai_polish
                else "Type the full announcement body exactly as you want it posted"
            ),
            required=True,
            max_length=1500,
        )
        self.add_item(self.draft)

        self.ann_number = discord.ui.TextInput(
            label="Announcement number",
            placeholder="e.g. 1 (this becomes SC-2026-001 automatically)",
            required=True,
            max_length=10,
        )
        self.add_item(self.ann_number)

        self.user_name = discord.ui.TextInput(
            label="Your name / username",
            required=True,
            max_length=50,
        )
        self.add_item(self.user_name)

        self.rank = discord.ui.TextInput(
            label="Your rank",
            required=True,
            max_length=50,
        )
        self.add_item(self.rank)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)

        if self.ai_polish:
            try:
                title, body = polish_text(self.draft.value)
            except Exception as e:
                await interaction.followup.send(
                    f"❌ Failed to reach the AI service: {e}", ephemeral=True
                )
                return
        else:
            title = self.title_input.value.strip()
            body = self.draft.value.strip()

        timestamp = int(time.time())
        current_year = datetime.now().year

        # Build the number part (pad to 3 digits if it's a plain number, e.g. "1" -> "001")
        raw_number = self.ann_number.value.strip()
        if raw_number.isdigit():
            number_part = raw_number.zfill(3)
        else:
            number_part = raw_number  # fallback if they type something non-numeric

        full_ann_number = f"SC-{current_year}-{number_part}"

        message_to_post, preview_text = build_message(
            title=title,
            body=body,
            ann_number=full_ann_number,
            timestamp=timestamp,
            user_name=self.user_name.value,
            rank=self.rank.value,
            ping_mention=self.ping_mention,
        )

        view = ConfirmView(
            title=title,
            body=body,
            ann_number=full_ann_number,
            timestamp=timestamp,
            user_name=self.user_name.value,
            rank=self.rank.value,
            ping_mention=self.ping_mention,
            image_bytes=self.image_bytes,
            image_filename=self.image_filename,
        )
        files = [discord.File(io.BytesIO(self.image_bytes), filename=self.image_filename)] if self.image_bytes else []
        await interaction.followup.send(
            f"**Preview:**\n\n{preview_text}",
            view=view,
            files=files,
            ephemeral=True,
        )


class EditModal(discord.ui.Modal, title="Edit Announcement Text"):
    def __init__(self, parent_view: "ConfirmView"):
        super().__init__()
        self.parent_view = parent_view

        # Pre-fill the fields with the current title/body so the user edits, not retypes
        self.edit_title = discord.ui.TextInput(
            label="Title",
            default=parent_view.title,
            required=True,
            max_length=100,
        )
        self.edit_body = discord.ui.TextInput(
            label="Body",
            style=discord.TextStyle.paragraph,
            default=parent_view.body,
            required=True,
            max_length=1800,
        )
        self.add_item(self.edit_title)
        self.add_item(self.edit_body)

    async def on_submit(self, interaction: discord.Interaction):
        # Update the parent view's stored text with the edited version
        self.parent_view.title = self.edit_title.value
        self.parent_view.body = self.edit_body.value

        message_to_post, preview_text = build_message(
            title=self.parent_view.title,
            body=self.parent_view.body,
            ann_number=self.parent_view.ann_number,
            timestamp=self.parent_view.timestamp,
            user_name=self.parent_view.user_name,
            rank=self.parent_view.rank,
            ping_mention=self.parent_view.ping_mention,
        )
        self.parent_view.message_to_post = message_to_post

        await interaction.response.edit_message(
            content=f"**Preview:**\n\n{preview_text}",
            view=self.parent_view,
        )


class ConfirmView(discord.ui.View):
    def __init__(self, title, body, ann_number, timestamp, user_name, rank, ping_mention, image_bytes=None, image_filename=None):
        super().__init__(timeout=300)
        self.title = title
        self.body = body
        self.ann_number = ann_number
        self.timestamp = timestamp
        self.user_name = user_name
        self.rank = rank
        self.ping_mention = ping_mention
        self.image_bytes = image_bytes
        self.image_filename = image_filename
        self.message_to_post, _ = build_message(
            title, body, ann_number, timestamp, user_name, rank, ping_mention
        )

    @discord.ui.button(label="Edit text", style=discord.ButtonStyle.blurple, emoji="✏️")
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EditModal(self))

    @discord.ui.button(label="Post to channel", style=discord.ButtonStyle.green, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        files = []
        if self.image_bytes:
            files.append(discord.File(io.BytesIO(self.image_bytes), filename=self.image_filename))

        await interaction.channel.send(
            self.message_to_post,
            files=files,
            allowed_mentions=discord.AllowedMentions(everyone=True, roles=True, users=True),
        )
        await interaction.response.edit_message(content="✅ Posted!", view=None, attachments=[])

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
        image="Optional image to attach (screenshot, tutorial graphic, etc.)",
        ai_polish="Rewrite your draft with AI (default: on). Turn off to post your text exactly as typed.",
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
        image: discord.Attachment = None,
        ai_polish: bool = True,
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

        image_bytes = None
        image_filename = None
        if image is not None:
            image_bytes = await image.read()
            image_filename = image.filename

        await interaction.response.send_modal(
            AnnounceModal(
                ping_mention=ping_mention,
                image_bytes=image_bytes,
                image_filename=image_filename,
                ai_polish=ai_polish,
            )
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Announce(bot))