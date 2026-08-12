"""
/announce command
------------------
Opens a popup form (draft, announcement number, name, rank), fills in
the template, and posts the result to the channel. AI polishing (via
Groq's free API) is on by default but can be turned off with the
`ai_polish` option - in that case you type the title and body exactly
as you want them posted, no rewriting.

Placeholders (work in both the draft and the title/body, with AI
polish on or off - they always survive AI polish untouched):
  {#channel-name}         -> a clickable link to that channel, never pings
  {@role or user name}    -> a clickable tag for that role/user, never pings
  {invite}                 -> a fresh invite link to the channel this is posted in
  {invite:Partner Name}    -> the saved invite link for a partner server
                              (must already exist in /partner add)

Only the ping chosen in the command's `ping`/`role` options actually
sends a notification - anything inserted via a placeholder is silent.
"""

import os
import re
import io
import json
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
— **{division}**
🛰️ {server_name}"""


# Edit this list to match your server's actual divisions/commands.
# "custom" always gets added automatically as the last dropdown option.
DIVISIONS = ["Supreme Command", "Lead Command", "High Command", "Development Bureau", "Imperial Security Bureau", "Partnership Bureau", "Management Team"]
DEFAULT_DIVISION = DIVISIONS[0]


MENTION_PLACEHOLDER = re.compile(r"\{(#|@)([^{}]+)\}")
INVITE_PLACEHOLDER = re.compile(r"\{invite(?::([^{}]+))?\}")
PARTNER_DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "partner_data.json")


def load_partner_links() -> dict:
    """name (lowercase) -> invite link, reusing the same data /partner add builds."""
    if not os.path.exists(PARTNER_DATA_FILE):
        return {}
    with open(PARTNER_DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {p["name"].strip().lower(): p["link"] for p in data.get("partners", [])}


async def resolve_invites(channel: discord.abc.GuildChannel, text: str) -> tuple[str, list[str]]:
    """
    {invite}          -> a fresh invite link to `channel` (this server)
    {invite:Name}      -> the saved invite link for a partner server from /partner add
    """
    unresolved = []
    partner_links = load_partner_links()

    pieces = []
    last_end = 0
    for match in INVITE_PLACEHOLDER.finditer(text):
        pieces.append(text[last_end:match.start()])
        name = match.group(1)

        if name:
            link = partner_links.get(name.strip().lower())
            if link:
                pieces.append(link)
            else:
                unresolved.append(match.group(0))
                pieces.append(match.group(0))
        else:
            try:
                invite = await channel.create_invite(max_age=0, max_uses=0, reason="Announcement invite link")
                pieces.append(invite.url)
            except discord.HTTPException:
                unresolved.append(match.group(0))
                pieces.append(match.group(0))

        last_end = match.end()
    pieces.append(text[last_end:])

    return "".join(pieces), unresolved


def _find_channel(guild: discord.Guild, name: str):
    """Exact name match first; falls back to 'contains' so decorated names
    like 🔑丨verify still match when someone types just {#verify}."""
    slug = name.lower().replace(" ", "-")
    exact = discord.utils.find(lambda c: c.name.lower() == slug, guild.text_channels)
    if exact is not None:
        return exact
    return discord.utils.find(lambda c: slug in c.name.lower(), guild.text_channels)


def _find_role_or_member(guild: discord.Guild, name: str):
    """Exact name match first (role, then member); falls back to 'contains'
    so decorated names like 🔰 Cadet still match when someone types {@Cadet}."""
    lname = name.lower()

    exact = discord.utils.find(lambda r: r.name.lower() == lname, guild.roles)
    if exact is not None:
        return exact
    exact = discord.utils.find(
        lambda m: m.display_name.lower() == lname or m.name.lower() == lname, guild.members
    )
    if exact is not None:
        return exact

    partial = discord.utils.find(lambda r: lname in r.name.lower(), guild.roles)
    if partial is not None:
        return partial
    return discord.utils.find(
        lambda m: lname in m.display_name.lower() or lname in m.name.lower(), guild.members
    )


async def resolve_placeholders(guild: discord.Guild, channel: discord.abc.GuildChannel, text: str) -> tuple[str, list[str]]:
    """
    Turns typed placeholders into real Discord references. None of these
    ever ping on their own - only the ping chosen in the command options does:
      {#channel-name}       -> a clickable channel link
      {@role or user name}  -> a clickable role/user tag, shown silently
      {invite}                -> a fresh invite link to this server
      {invite:Partner Name}   -> the saved invite link for a partner server (from /partner add)
    Returns (resolved_text, list_of_placeholders_that_could_not_be_matched).
    """
    unresolved = []

    def repl(match: re.Match) -> str:
        kind, name = match.group(1), match.group(2).strip()
        original = match.group(0)

        if kind == "#":
            target = _find_channel(guild, name)
        else:  # "@"
            target = _find_role_or_member(guild, name)

        if target is not None:
            return target.mention

        unresolved.append(original)
        return original

    resolved = MENTION_PLACEHOLDER.sub(repl, text)
    resolved, invite_unresolved = await resolve_invites(channel, resolved)
    unresolved.extend(invite_unresolved)

    return resolved, unresolved


def build_allowed_mentions(ping_value: str, ping_role: discord.Role = None) -> discord.AllowedMentions:
    """Only the explicitly selected ping target actually notifies anyone.
    Role/user mentions inserted via {@name} placeholders always stay silent."""
    if ping_value in ("everyone", "here"):
        return discord.AllowedMentions(everyone=True, roles=False, users=False)
    if ping_value == "role" and ping_role:
        return discord.AllowedMentions(everyone=False, roles=[ping_role], users=False)
    return discord.AllowedMentions(everyone=False, roles=False, users=False)


PLACEHOLDER_TOKEN_PATTERN = re.compile(r"\{(?:#|@)[^{}]+\}|\{invite(?::[^{}]+)?\}")


def tokenize_placeholders(text: str) -> tuple[str, dict[str, str]]:
    """
    Swaps every {#...}/{@...}/{invite...} placeholder for an opaque
    [[PLACEHOLDER_n]] token before the text is sent to the AI. The AI can't
    "helpfully" auto-correct a name (e.g. {@Superluks} -> {@Superluks5}) if
    it never sees the real placeholder text in the first place.
    Returns (text_with_tokens, {token: original_placeholder_text}).
    """
    mapping: dict[str, str] = {}

    def repl(match: re.Match) -> str:
        token = f"[[PLACEHOLDER_{len(mapping)}]]"
        mapping[token] = match.group(0)
        return token

    return PLACEHOLDER_TOKEN_PATTERN.sub(repl, text), mapping


def restore_placeholders(text: str, mapping: dict[str, str]) -> str:
    for token, original in mapping.items():
        text = text.replace(token, original)
    return text


def polish_text(draft: str) -> tuple[str, str]:
    prompt = f"""You are helping write a professional Discord server announcement
for a Star Wars themed Roblox game community taking place in the Imperial Timeline. (Roblox Game is in Development) Take the rough draft below and:

1. Write a short, clear title (no more than 6 words, no emojis, no quotes around it)
2. Rewrite the body in clear, professional, concise language. Keep it friendly
   but not overly casual. Do not add a greeting like "Hello everyone". Do not
   add a signature or sign-off. Do not use markdown headers. And do not add any emojis. It has to be suitable for a Discord announcement channel. And it has to be suitable for a Star Wars themed Roblox game community. Do not add any extra information that is not in the draft. Do not make up any new information. Keep it concise and to the point. It has to have same meaning as the draft. Do not add any extra information that is not in the draft. Do not make up any new information. Keep it concise and to the point. It has to have same meaning as the draft.
3. The draft may contain tokens that look like [[PLACEHOLDER_0]],
   [[PLACEHOLDER_1]], etc. Copy any such token into your rewrite EXACTLY as it
   appears, character for character, keeping it in the same relative place in
   the sentence. Never translate, reword, remove, "fix", or alter these
   tokens in any way - not even the numbers inside them.

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


def build_message(title, body, ann_number, timestamp, user_name, rank, ping_mention, division=DEFAULT_DIVISION):
    """Build the final formatted message and its preview text from all the pieces."""
    final_message = TEMPLATE.format(
        title=title,
        body=body,
        ann_number=ann_number,
        timestamp=timestamp,
        user_name=user_name,
        rank=rank,
        division=division,
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
    def __init__(
        self,
        ping_mention: str = "",
        ping_value: str = "none",
        ping_role: discord.Role = None,
        image_bytes: bytes = None,
        image_filename: str = None,
        ai_polish: bool = True,
        division: str = DEFAULT_DIVISION,
    ):
        super().__init__()
        self.ping_mention = ping_mention
        self.ping_value = ping_value
        self.ping_role = ping_role
        self.image_bytes = image_bytes
        self.image_filename = image_filename
        self.ai_polish = ai_polish
        self.division = division

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
                "e.g. server update, new planets added, use {#verify} {@Cadet} {invite}"
                if ai_polish
                else "Type the full body. {#chan} {@role} {invite} placeholders work here too"
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
                tokenized_draft, token_map = tokenize_placeholders(self.draft.value)
                title, body = polish_text(tokenized_draft)
                title = restore_placeholders(title, token_map)
                body = restore_placeholders(body, token_map)
            except Exception as e:
                await interaction.followup.send(
                    f"❌ Failed to reach the AI service: {e}", ephemeral=True
                )
                return
        else:
            title = self.title_input.value.strip()
            body = self.draft.value.strip()

        title, unresolved_title = await resolve_placeholders(interaction.guild, interaction.channel, title)
        body, unresolved_body = await resolve_placeholders(interaction.guild, interaction.channel, body)
        unresolved = unresolved_title + unresolved_body

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
            division=self.division,
        )

        view = ConfirmView(
            title=title,
            body=body,
            ann_number=full_ann_number,
            timestamp=timestamp,
            user_name=self.user_name.value,
            rank=self.rank.value,
            ping_mention=self.ping_mention,
            ping_value=self.ping_value,
            ping_role=self.ping_role,
            division=self.division,
            image_bytes=self.image_bytes,
            image_filename=self.image_filename,
        )
        files = [discord.File(io.BytesIO(self.image_bytes), filename=self.image_filename)] if self.image_bytes else []
        warning = (
            f"\n\n⚠️ Couldn't match: {', '.join(unresolved)} — check the spelling, "
            f"or that it exists in this server."
            if unresolved
            else ""
        )
        await interaction.followup.send(
            f"**Preview:**\n\n{preview_text}{warning}",
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
        resolved_title, unresolved_title = await resolve_placeholders(
            interaction.guild, interaction.channel, self.edit_title.value
        )
        resolved_body, unresolved_body = await resolve_placeholders(
            interaction.guild, interaction.channel, self.edit_body.value
        )
        unresolved = unresolved_title + unresolved_body

        # Update the parent view's stored text with the edited (and resolved) version
        self.parent_view.title = resolved_title
        self.parent_view.body = resolved_body

        message_to_post, preview_text = build_message(
            title=self.parent_view.title,
            body=self.parent_view.body,
            ann_number=self.parent_view.ann_number,
            timestamp=self.parent_view.timestamp,
            user_name=self.parent_view.user_name,
            rank=self.parent_view.rank,
            ping_mention=self.parent_view.ping_mention,
            division=self.parent_view.division,
        )
        self.parent_view.message_to_post = message_to_post

        await interaction.response.edit_message(
            content=f"**Preview:**\n\n{preview_text}",
            view=self.parent_view,
        )

        if unresolved:
            await interaction.followup.send(
                f"⚠️ Couldn't match: {', '.join(unresolved)} — check the spelling, "
                f"or that it exists in this server.",
                ephemeral=True,
            )


class ConfirmView(discord.ui.View):
    def __init__(
        self,
        title,
        body,
        ann_number,
        timestamp,
        user_name,
        rank,
        ping_mention,
        ping_value="none",
        ping_role=None,
        division=DEFAULT_DIVISION,
        image_bytes=None,
        image_filename=None,
    ):
        super().__init__(timeout=300)
        self.title = title
        self.body = body
        self.ann_number = ann_number
        self.timestamp = timestamp
        self.user_name = user_name
        self.rank = rank
        self.ping_mention = ping_mention
        self.ping_value = ping_value
        self.ping_role = ping_role
        self.division = division
        self.image_bytes = image_bytes
        self.image_filename = image_filename
        self.message_to_post, _ = build_message(
            title, body, ann_number, timestamp, user_name, rank, ping_mention, division
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
            allowed_mentions=build_allowed_mentions(self.ping_value, self.ping_role),
        )
        await interaction.response.edit_message(content="✅ Posted!", view=None, attachments=[])

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="❌ Cancelled. Nothing was posted.", view=None)


PLACEHOLDER_HELP = (
    "**Available placeholders** — type these anywhere in your draft/title/body. "
    "None of them ping (only your `ping`/`role` choice above does), and they "
    "survive AI polish untouched:\n"
    "`{#channel-name}` — clickable link to that channel\n"
    "`{@role or user name}` — clickable tag for that role/user, shown silently\n"
    "`{invite}` — fresh invite link to this server\n"
    "`{invite:Partner Name}` — saved invite link for a partner server (must already exist in `/partner add`)"
)


class CustomDivisionModal(discord.ui.Modal, title="Custom Signing Line"):
    """One-field modal shown only when 'Custom...' is picked in the division
    dropdown. Submitting it immediately opens the main announcement form -
    modal-to-modal chaining works because each submission is a fresh interaction."""

    def __init__(self, ping_mention, ping_value, ping_role, image_bytes, image_filename, ai_polish):
        super().__init__()
        self.ping_mention = ping_mention
        self.ping_value = ping_value
        self.ping_role = ping_role
        self.image_bytes = image_bytes
        self.image_filename = image_filename
        self.ai_polish = ai_polish

        self.division_input = discord.ui.TextInput(
            label="Signing line",
            placeholder="e.g. Naval Command, COMPNOR, 501st Legion",
            required=True,
            max_length=50,
        )
        self.add_item(self.division_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_modal(
            AnnounceModal(
                ping_mention=self.ping_mention,
                ping_value=self.ping_value,
                ping_role=self.ping_role,
                image_bytes=self.image_bytes,
                image_filename=self.image_filename,
                ai_polish=self.ai_polish,
                division=self.division_input.value.strip(),
            )
        )


class OpenFormView(discord.ui.View):
    """Shown before the modal so the placeholder cheat sheet has room to display -
    modals can't hold a block of help text, only short per-field hints. The
    signing-line dropdown lives here too, since modals can't contain dropdowns."""

    def __init__(self, ping_mention, ping_value, ping_role, image_bytes, image_filename, ai_polish):
        super().__init__(timeout=300)
        self.ping_mention = ping_mention
        self.ping_value = ping_value
        self.ping_role = ping_role
        self.image_bytes = image_bytes
        self.image_filename = image_filename
        self.ai_polish = ai_polish
        self.division = DEFAULT_DIVISION

        options = [
            discord.SelectOption(label=name, default=(name == DEFAULT_DIVISION)) for name in DIVISIONS
        ]
        options.append(discord.SelectOption(label="Custom...", value="custom"))
        self.division_select.options = options

    @discord.ui.select(placeholder=f"Signing line: {DEFAULT_DIVISION}", options=[])
    async def division_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.division = select.values[0]
        label = "Custom (you'll be asked to type it next)" if self.division == "custom" else self.division
        for option in select.options:
            option.default = option.value == self.division
        await interaction.response.edit_message(
            content=f"{PLACEHOLDER_HELP}\n\n**Signing line:** {label}",
            view=self,
        )

    @discord.ui.button(label="Open announcement form", style=discord.ButtonStyle.blurple, emoji="📝")
    async def open_form(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.division == "custom":
            await interaction.response.send_modal(
                CustomDivisionModal(
                    ping_mention=self.ping_mention,
                    ping_value=self.ping_value,
                    ping_role=self.ping_role,
                    image_bytes=self.image_bytes,
                    image_filename=self.image_filename,
                    ai_polish=self.ai_polish,
                )
            )
            return

        await interaction.response.send_modal(
            AnnounceModal(
                ping_mention=self.ping_mention,
                ping_value=self.ping_value,
                ping_role=self.ping_role,
                image_bytes=self.image_bytes,
                image_filename=self.image_filename,
                ai_polish=self.ai_polish,
                division=self.division,
            )
        )


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

        await interaction.response.send_message(
            PLACEHOLDER_HELP,
            view=OpenFormView(
                ping_mention=ping_mention,
                ping_value=ping_value,
                ping_role=role,
                image_bytes=image_bytes,
                image_filename=image_filename,
                ai_polish=ai_polish,
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Announce(bot))