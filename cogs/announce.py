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

Per-server settings (guild_data/<guild_id>/announce_config.json):
  - "divisions": the signing-line/rank dropdown options - configurable
    per server via /announce-config divisions-add / divisions-remove /
    divisions-list, instead of editing code.
  - "ai_enabled": lets a server turn AI polishing off entirely via
    /announce-config ai, regardless of what a user picks in the command.
  - "groq_api_key": a server's own Groq key (from /announce-config
    groq-key-set), used instead of the bot-wide shared key from the
    GROQ_API_KEY env var. /announce-config groq-key-clear removes it.
The server name shown in the posted announcement is always the live
Discord server name (guild.name) - no per-server setup needed for that.
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

from guild_paths import guild_file

# Shared bot-wide fallback key - used for any server that hasn't set its
# own key via /announce-config groq-key-set.
FALLBACK_GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
MODEL = "openai/gpt-oss-120b"  # llama-3.3-70b-versatile was decommissioned by Groq on Aug 16, 2026

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


# Seed divisions used only the first time a server's announce_config.json
# is created. After that, each server's list is edited via
# /announce-config divisions-add / divisions-remove, not by editing code.
DEFAULT_DIVISIONS = ["Supreme Command", "High Command", "Naval Command", "Intelligence Bureau"]

DEFAULT_ANNOUNCE_CONFIG = {
    "divisions": DEFAULT_DIVISIONS,
    "ai_enabled": True,
    "groq_api_key": None,
}

# Discord select menus cap at 25 options; one slot is always reserved for
# the "Custom..." entry the dropdown adds automatically.
MAX_DIVISIONS = 24


def load_announce_config(guild_id: int) -> dict:
    path = guild_file(guild_id, "announce_config.json")
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_ANNOUNCE_CONFIG, f, indent=2)
        return dict(DEFAULT_ANNOUNCE_CONFIG)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    merged = dict(DEFAULT_ANNOUNCE_CONFIG)
    merged.update(data)
    return merged


def save_announce_config(guild_id: int, config: dict) -> None:
    path = guild_file(guild_id, "announce_config.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def get_groq_client(config: dict) -> Groq | None:
    """Server's own key if set, else the shared fallback key. None if
    neither is available (AI polish can't run for this server)."""
    key = config.get("groq_api_key") or FALLBACK_GROQ_API_KEY
    if not key:
        return None
    return Groq(api_key=key)


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


def polish_text(draft: str, client: Groq) -> tuple[str, str]:
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

    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
        reasoning_effort="low",
        reasoning_format="hidden",
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


def build_message(title, body, ann_number, timestamp, user_name, rank, ping_mention, server_name, division):
    """Build the final formatted message and its preview text from all the pieces.
    server_name and division are always passed in explicitly by the caller -
    server_name is the live guild.name, division comes from that server's
    configured divisions list (or a custom signing line the user typed)."""
    final_message = TEMPLATE.format(
        title=title,
        body=body,
        ann_number=ann_number,
        timestamp=timestamp,
        user_name=user_name,
        rank=rank,
        division=division,
        server_name=server_name,
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
        server_name: str,
        ping_mention: str = "",
        ping_value: str = "none",
        ping_role: discord.Role = None,
        image_bytes: bytes = None,
        image_filename: str = None,
        ai_polish: bool = True,
        division: str = None,
    ):
        super().__init__()
        self.server_name = server_name
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
            config = load_announce_config(interaction.guild.id)
            client = get_groq_client(config)
            if client is None:
                # Shouldn't normally happen (the command already checks this),
                # but if it does, fail gracefully instead of erroring out.
                await interaction.followup.send(
                    "❌ AI polishing isn't available for this server - no Groq API key is "
                    "configured. Ask an admin to run `/announce-config groq-key-set`, or "
                    "rerun with `ai_polish` off.",
                    ephemeral=True,
                )
                return
            try:
                tokenized_draft, token_map = tokenize_placeholders(self.draft.value)
                title, body = polish_text(tokenized_draft, client)
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
            server_name=self.server_name,
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
            server_name=self.server_name,
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
            server_name=self.parent_view.server_name,
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
        server_name,
        division,
        ping_value="none",
        ping_role=None,
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
        self.server_name = server_name
        self.division = division
        self.image_bytes = image_bytes
        self.image_filename = image_filename
        self.message_to_post, _ = build_message(
            title, body, ann_number, timestamp, user_name, rank, ping_mention, server_name, division
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

    def __init__(self, server_name, ping_mention, ping_value, ping_role, image_bytes, image_filename, ai_polish):
        super().__init__()
        self.server_name = server_name
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
                server_name=self.server_name,
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

    def __init__(self, server_name, divisions, ping_mention, ping_value, ping_role, image_bytes, image_filename, ai_polish):
        super().__init__(timeout=300)
        self.server_name = server_name
        self.divisions = divisions
        self.ping_mention = ping_mention
        self.ping_value = ping_value
        self.ping_role = ping_role
        self.image_bytes = image_bytes
        self.image_filename = image_filename
        self.ai_polish = ai_polish
        self.division = divisions[0]

        options = [
            discord.SelectOption(label=name, default=(name == self.division)) for name in divisions
        ]
        options.append(discord.SelectOption(label="Custom...", value="custom"))
        self.division_select.options = options
        self.division_select.placeholder = f"Signing line: {self.division}"

    @discord.ui.select(placeholder="Signing line", options=[])
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
                    server_name=self.server_name,
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
                server_name=self.server_name,
                ping_mention=self.ping_mention,
                ping_value=self.ping_value,
                ping_role=self.ping_role,
                image_bytes=self.image_bytes,
                image_filename=self.image_filename,
                ai_polish=self.ai_polish,
                division=self.division,
            )
        )


def _is_admin(interaction: discord.Interaction) -> bool:
    return interaction.user.guild_permissions.administrator


ADMIN_ONLY_MESSAGE = "⚠️ Only server administrators can change this."


class Announce(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ------------------------------------------------------------------
    # /scannounce
    # ------------------------------------------------------------------
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

        config = load_announce_config(interaction.guild.id)
        divisions = config.get("divisions") or DEFAULT_DIVISIONS

        # Server-level AI setting always wins over the user's ai_polish choice.
        effective_ai_polish = ai_polish and config.get("ai_enabled", True)
        note = ""
        if ai_polish and not config.get("ai_enabled", True):
            note = "\n\n*(AI polishing is turned off for this server - posting your draft as typed.)*"
        elif effective_ai_polish and get_groq_client(config) is None:
            effective_ai_polish = False
            note = (
                "\n\n*(AI polishing is on but no Groq API key is set for this server - "
                "posting your draft as typed. An admin can add one with "
                "`/announce-config groq-key-set`.)*"
            )

        await interaction.response.send_message(
            PLACEHOLDER_HELP + note,
            view=OpenFormView(
                server_name=interaction.guild.name,
                divisions=divisions,
                ping_mention=ping_mention,
                ping_value=ping_value,
                ping_role=role,
                image_bytes=image_bytes,
                image_filename=image_filename,
                ai_polish=effective_ai_polish,
            ),
            ephemeral=True,
        )

    # ------------------------------------------------------------------
    # /announce-config - per-server settings, admin only
    # ------------------------------------------------------------------
    config_group = app_commands.Group(
        name="announce-config",
        description="Configure /scannounce for this server (admin only)",
    )

    @config_group.command(name="divisions-list", description="Show this server's signing-line/division options")
    async def divisions_list(self, interaction: discord.Interaction):
        config = load_announce_config(interaction.guild.id)
        divisions = config.get("divisions") or DEFAULT_DIVISIONS
        await interaction.response.send_message(
            "**Divisions for this server:**\n" + "\n".join(f"- {d}" for d in divisions),
            ephemeral=True,
        )

    @config_group.command(name="divisions-add", description="Add a signing-line/division option for this server")
    @app_commands.describe(name="Division/rank name to add, e.g. 'Naval Command'")
    async def divisions_add(self, interaction: discord.Interaction, name: str):
        if not _is_admin(interaction):
            await interaction.response.send_message(ADMIN_ONLY_MESSAGE, ephemeral=True)
            return

        name = name.strip()
        config = load_announce_config(interaction.guild.id)
        divisions = config.get("divisions") or list(DEFAULT_DIVISIONS)

        if any(d.lower() == name.lower() for d in divisions):
            await interaction.response.send_message(f"⚠️ '{name}' is already in the list.", ephemeral=True)
            return
        if len(divisions) >= MAX_DIVISIONS:
            await interaction.response.send_message(
                f"⚠️ Max {MAX_DIVISIONS} divisions (Discord's dropdown limit, with one slot "
                "reserved for 'Custom...'). Remove one first with `/announce-config divisions-remove`.",
                ephemeral=True,
            )
            return

        divisions.append(name)
        config["divisions"] = divisions
        save_announce_config(interaction.guild.id, config)
        await interaction.response.send_message(
            f"✅ Added '{name}'.\n\n**Current list:**\n" + "\n".join(f"- {d}" for d in divisions),
            ephemeral=True,
        )

    @config_group.command(name="divisions-remove", description="Remove a signing-line/division option for this server")
    @app_commands.describe(name="Division/rank name to remove, exactly as it appears in divisions-list")
    async def divisions_remove(self, interaction: discord.Interaction, name: str):
        if not _is_admin(interaction):
            await interaction.response.send_message(ADMIN_ONLY_MESSAGE, ephemeral=True)
            return

        config = load_announce_config(interaction.guild.id)
        divisions = config.get("divisions") or list(DEFAULT_DIVISIONS)
        match = discord.utils.find(lambda d: d.lower() == name.strip().lower(), divisions)

        if match is None:
            await interaction.response.send_message(
                f"⚠️ '{name}' isn't in the list. Check `/announce-config divisions-list` for exact spelling.",
                ephemeral=True,
            )
            return
        if len(divisions) == 1:
            await interaction.response.send_message(
                "⚠️ Can't remove the last division - add a replacement first with `divisions-add`.",
                ephemeral=True,
            )
            return

        divisions.remove(match)
        config["divisions"] = divisions
        save_announce_config(interaction.guild.id, config)
        await interaction.response.send_message(
            f"✅ Removed '{match}'.\n\n**Current list:**\n" + "\n".join(f"- {d}" for d in divisions),
            ephemeral=True,
        )

    @config_group.command(name="ai", description="Turn AI polishing on or off for this server")
    @app_commands.describe(enabled="Allow /scannounce to use AI polishing in this server")
    async def ai_toggle(self, interaction: discord.Interaction, enabled: bool):
        if not _is_admin(interaction):
            await interaction.response.send_message(ADMIN_ONLY_MESSAGE, ephemeral=True)
            return

        config = load_announce_config(interaction.guild.id)
        config["ai_enabled"] = enabled
        save_announce_config(interaction.guild.id, config)
        state = "enabled" if enabled else "disabled"
        await interaction.response.send_message(f"✅ AI polishing is now **{state}** for this server.", ephemeral=True)

    @config_group.command(name="groq-key-set", description="Set this server's own Groq API key for AI polishing")
    @app_commands.describe(key="Your Groq API key from console.groq.com")
    async def groq_key_set(self, interaction: discord.Interaction, key: str):
        if not _is_admin(interaction):
            await interaction.response.send_message(ADMIN_ONLY_MESSAGE, ephemeral=True)
            return

        config = load_announce_config(interaction.guild.id)
        config["groq_api_key"] = key.strip()
        save_announce_config(interaction.guild.id, config)
        await interaction.response.send_message(
            "✅ Groq API key saved for this server - it'll be used instead of the shared key from now on. "
            "(This reply is only visible to you.)",
            ephemeral=True,
        )

    @config_group.command(name="groq-key-clear", description="Remove this server's own Groq API key (falls back to the shared key, if any)")
    async def groq_key_clear(self, interaction: discord.Interaction):
        if not _is_admin(interaction):
            await interaction.response.send_message(ADMIN_ONLY_MESSAGE, ephemeral=True)
            return

        config = load_announce_config(interaction.guild.id)
        config["groq_api_key"] = None
        save_announce_config(interaction.guild.id, config)
        fallback_note = " This server will now use the shared key." if FALLBACK_GROQ_API_KEY else " No shared key is configured, so AI polishing will be unavailable until a new key is set."
        await interaction.response.send_message(f"✅ Server-specific Groq key removed.{fallback_note}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Announce(bot))