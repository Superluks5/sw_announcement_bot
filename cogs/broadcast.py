"""
/broadcast command group
-------------------------
Same drafting flow as /announce (AI-polished text + your announcement
template), but schedules the post for a future time instead of sending
it right away. A background loop checks every minute for anything due
and posts it automatically - this keeps working even across restarts,
since everything is saved to broadcast_data.json.

Subcommands:
  /broadcast schedule  - draft + schedule an announcement for later
  /broadcast list      - see everything still pending
  /broadcast cancel    - cancel a pending broadcast before it posts
"""

import os
import io
import json
import time
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands, tasks

from .announce import polish_text, build_message

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "broadcast_data.json")
IMAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "broadcast_images")

DELAY_CHOICES = [
    app_commands.Choice(name="30 minutes", value=30),
    app_commands.Choice(name="1 hour", value=60),
    app_commands.Choice(name="3 hours", value=180),
    app_commands.Choice(name="6 hours", value=360),
    app_commands.Choice(name="12 hours", value=720),
    app_commands.Choice(name="Tomorrow (24h)", value=1440),
    app_commands.Choice(name="Custom", value=-1),
]


def load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        return {"next_id": 1, "scheduled": []}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("next_id", 1)
    data.setdefault("scheduled", [])
    return data


def save_data(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def save_image(broadcast_id: int, image_bytes: bytes, filename: str) -> str:
    os.makedirs(IMAGE_DIR, exist_ok=True)
    ext = os.path.splitext(filename)[1] or ".png"
    path = os.path.join(IMAGE_DIR, f"{broadcast_id}{ext}")
    with open(path, "wb") as f:
        f.write(image_bytes)
    return path


class EditModal(discord.ui.Modal, title="Edit Broadcast Text"):
    def __init__(self, parent_view: "ScheduleConfirmView"):
        super().__init__()
        self.parent_view = parent_view

        self.edit_title = discord.ui.TextInput(
            label="Title", default=parent_view.title, required=True, max_length=100,
        )
        self.edit_body = discord.ui.TextInput(
            label="Body", style=discord.TextStyle.paragraph,
            default=parent_view.body, required=True, max_length=1800,
        )
        self.add_item(self.edit_title)
        self.add_item(self.edit_body)

    async def on_submit(self, interaction: discord.Interaction):
        self.parent_view.title = self.edit_title.value
        self.parent_view.body = self.edit_body.value
        preview_text = self.parent_view.build_preview()
        await interaction.response.edit_message(
            content=f"**Preview** — will post <t:{self.parent_view.post_at}:R>:\n\n{preview_text}",
            view=self.parent_view,
        )


class ScheduleConfirmView(discord.ui.View):
    def __init__(self, title, body, ann_number, user_name, rank, ping_mention,
                 channel_id, creator_id, post_at, image_bytes=None, image_filename=None):
        super().__init__(timeout=300)
        self.title = title
        self.body = body
        self.ann_number = ann_number
        self.user_name = user_name
        self.rank = rank
        self.ping_mention = ping_mention
        self.channel_id = channel_id
        self.creator_id = creator_id
        self.post_at = post_at
        self.image_bytes = image_bytes
        self.image_filename = image_filename
        self.message_to_post = None

    def build_preview(self) -> str:
        message_to_post, preview_text = build_message(
            title=self.title, body=self.body, ann_number=self.ann_number,
            timestamp=self.post_at, user_name=self.user_name, rank=self.rank,
            ping_mention=self.ping_mention,
        )
        self.message_to_post = message_to_post
        return preview_text

    @discord.ui.button(label="Edit text", style=discord.ButtonStyle.blurple, emoji="✏️")
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EditModal(self))

    @discord.ui.button(label="Schedule", style=discord.ButtonStyle.green, emoji="🗓️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = load_data()
        broadcast_id = data["next_id"]
        data["next_id"] += 1

        image_path = None
        if self.image_bytes:
            image_path = save_image(broadcast_id, self.image_bytes, self.image_filename)

        data["scheduled"].append({
            "id": broadcast_id,
            "post_at": self.post_at,
            "channel_id": self.channel_id,
            "creator_id": self.creator_id,
            "title": self.title,
            "body": self.body,
            "ann_number": self.ann_number,
            "user_name": self.user_name,
            "rank": self.rank,
            "ping_mention": self.ping_mention,
            "image_path": image_path,
            "image_filename": self.image_filename,
        })
        save_data(data)

        await interaction.response.edit_message(
            content=(
                f"🗓️ Scheduled as broadcast `#{broadcast_id}` — posts <t:{self.post_at}:R> "
                f"(<t:{self.post_at}:F>)."
            ),
            view=None,
            attachments=[],
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="❌ Cancelled. Nothing was scheduled.", view=None)


class BroadcastModal(discord.ui.Modal, title="New Broadcast"):
    def __init__(self, post_at: int, ping_mention: str = "", image_bytes: bytes = None, image_filename: str = None):
        super().__init__()
        self.post_at = post_at
        self.ping_mention = ping_mention
        self.image_bytes = image_bytes
        self.image_filename = image_filename

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
    user_name = discord.ui.TextInput(label="Your name / username", required=True, max_length=50)
    rank = discord.ui.TextInput(label="Your rank", required=True, max_length=50)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)

        try:
            title, body = polish_text(self.draft.value)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to reach the AI service: {e}", ephemeral=True)
            return

        current_year = datetime.now().year
        raw_number = self.ann_number.value.strip()
        number_part = raw_number.zfill(3) if raw_number.isdigit() else raw_number
        full_ann_number = f"SC-{current_year}-{number_part}"

        view = ScheduleConfirmView(
            title=title,
            body=body,
            ann_number=full_ann_number,
            user_name=self.user_name.value,
            rank=self.rank.value,
            ping_mention=self.ping_mention,
            channel_id=interaction.channel_id,
            creator_id=interaction.user.id,
            post_at=self.post_at,
            image_bytes=self.image_bytes,
            image_filename=self.image_filename,
        )
        preview_text = view.build_preview()
        files = [discord.File(io.BytesIO(self.image_bytes), filename=self.image_filename)] if self.image_bytes else []
        await interaction.followup.send(
            f"**Preview** — will post <t:{self.post_at}:R>:\n\n{preview_text}",
            view=view,
            files=files,
            ephemeral=True,
        )


class Broadcast(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_due_broadcasts.start()

    def cog_unload(self):
        self.check_due_broadcasts.cancel()

    broadcast_group = app_commands.Group(name="broadcast", description="Schedule announcements for later")

    @tasks.loop(seconds=60)
    async def check_due_broadcasts(self):
        data = load_data()
        now = time.time()
        due = [b for b in data["scheduled"] if b["post_at"] <= now]
        if not due:
            return

        for b in due:
            channel = self.bot.get_channel(b["channel_id"])
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(b["channel_id"])
                except discord.HTTPException:
                    channel = None

            if channel is not None:
                message_to_post, _ = build_message(
                    title=b["title"], body=b["body"], ann_number=b["ann_number"],
                    timestamp=int(b["post_at"]), user_name=b["user_name"], rank=b["rank"],
                    ping_mention=b["ping_mention"],
                )
                files = []
                if b.get("image_path") and os.path.exists(b["image_path"]):
                    files.append(discord.File(b["image_path"], filename=b["image_filename"]))
                try:
                    await channel.send(
                        message_to_post,
                        files=files,
                        allowed_mentions=discord.AllowedMentions(everyone=True, roles=True, users=True),
                    )
                except discord.HTTPException as e:
                    print(f"⚠️ Failed to post scheduled broadcast #{b['id']}: {e}")

            if b.get("image_path") and os.path.exists(b["image_path"]):
                os.remove(b["image_path"])

        data["scheduled"] = [b for b in data["scheduled"] if b["post_at"] > now]
        save_data(data)

    @check_due_broadcasts.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    @broadcast_group.command(name="schedule", description="Draft and schedule an announcement for later")
    @app_commands.describe(
        when="How long from now to post it",
        custom_minutes="Only needed if you picked 'Custom' above - minutes from now",
        ping="Who should be pinged when it posts",
        role="Only needed if you picked 'Specific role' above",
        image="Optional image to attach (screenshot, tutorial graphic, etc.)",
    )
    @app_commands.choices(
        when=DELAY_CHOICES,
        ping=[
            app_commands.Choice(name="No ping", value="none"),
            app_commands.Choice(name="@everyone", value="everyone"),
            app_commands.Choice(name="@here", value="here"),
            app_commands.Choice(name="Specific role", value="role"),
        ],
    )
    async def schedule(
        self,
        interaction: discord.Interaction,
        when: app_commands.Choice[int],
        custom_minutes: app_commands.Range[int, 1, 10080] = None,
        ping: app_commands.Choice[str] = None,
        role: discord.Role = None,
        image: discord.Attachment = None,
    ):
        if when.value == -1:
            if custom_minutes is None:
                await interaction.response.send_message(
                    "⚠️ You picked 'Custom' but didn't set `custom_minutes`. Run the command again and fill it in.",
                    ephemeral=True,
                )
                return
            minutes = custom_minutes
        else:
            minutes = when.value

        post_at = int(time.time()) + minutes * 60

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
            BroadcastModal(
                post_at=post_at,
                ping_mention=ping_mention,
                image_bytes=image_bytes,
                image_filename=image_filename,
            )
        )

    @broadcast_group.command(name="list", description="See everything still pending")
    async def list_broadcasts(self, interaction: discord.Interaction):
        data = load_data()
        pending = sorted(data["scheduled"], key=lambda b: b["post_at"])

        if not pending:
            await interaction.response.send_message("Nothing scheduled right now.", ephemeral=True)
            return

        lines = [
            f"`#{b['id']}` {b['ann_number']} — \"{b['title']}\" — posts <t:{int(b['post_at'])}:R>"
            for b in pending
        ]
        embed = discord.Embed(
            title="🗓️ Pending Broadcasts",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @broadcast_group.command(name="cancel", description="Cancel a pending broadcast before it posts")
    @app_commands.describe(broadcast_id="The # shown in /broadcast list")
    async def cancel(self, interaction: discord.Interaction, broadcast_id: int):
        data = load_data()
        match = next((b for b in data["scheduled"] if b["id"] == broadcast_id), None)

        if not match:
            await interaction.response.send_message(
                f"⚠️ No pending broadcast with id `#{broadcast_id}`. Use `/broadcast list` to check.",
                ephemeral=True,
            )
            return

        if match.get("image_path") and os.path.exists(match["image_path"]):
            os.remove(match["image_path"])

        data["scheduled"].remove(match)
        save_data(data)
        await interaction.response.send_message(
            f"🗑️ Cancelled broadcast #{broadcast_id}: \"{match['title']}\"", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Broadcast(bot))
