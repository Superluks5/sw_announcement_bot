"""
Command permissions - edit permissions_config.json to control who can use
each command. This .py file holds the shared logic (tracked in git and
identical everywhere); the actual role IDs live in permissions_config.json,
which is gitignored so it can be different per machine (e.g. your real
server's role IDs on the VM vs a test server's role IDs on your local
dev clone) without git ever overwriting one with the other.

Since Discord's own permission menu (Server Settings -> Integrations) can
only restrict a whole command GROUP at once (e.g. all of /task together,
not /task add separately from /task show), this handles it in code
instead - down to the individual subcommand level.

HOW TO USE:
Open (or create) permissions_config.json in the same folder as this file.
The key is the command's "qualified name" - for a plain command it's just
the name (e.g. "duel"), for a subcommand it's "group subcommand" separated
by a space (e.g. "task add", "rank link"). The value is a list of Discord
role IDs (as strings) allowed to use it.

  - A command NOT listed is open to everyone (safe default - nothing
    breaks if you forget to add a new command).
  - A command listed with an EMPTY list [] is usable by nobody except admins.
  - Server admins (Administrator permission) can always use every command,
    regardless of what's listed, as long as ADMIN_BYPASS is True below.

To find a role's ID: enable Developer Mode in Discord (User Settings ->
Advanced), then right-click any role in Server Settings -> Roles -> Copy ID.

EXAMPLE permissions_config.json:
{
  "promote": ["123456789012345678"],
  "rank link": ["123456789012345678", "987654321098765432"],
  "task add": ["111111111111111111"],
  "task show": []
}

If permissions_config.json doesn't exist yet, it's auto-created empty
(everyone can use everything) the first time the bot runs.
"""

import os
import json
import discord

ADMIN_BYPASS = True

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "permissions_config.json")


def _load_config() -> dict[str, list[int]]:
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=2)
        return {}

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)

    # JSON can't hold ints this large reliably in all tools, so IDs are
    # stored as strings in the file and converted to int here for comparison.
    return {command: [int(role_id) for role_id in role_ids] for command, role_ids in raw.items()}


def is_command_allowed(interaction: discord.Interaction) -> bool:
    if interaction.command is None:
        return True

    if ADMIN_BYPASS and isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator:
        return True

    command_permissions = _load_config()
    allowed_role_ids = command_permissions.get(interaction.command.qualified_name)
    if allowed_role_ids is None:
        return True  # not listed - open to everyone

    if not isinstance(interaction.user, discord.Member):
        return False

    user_role_ids = {r.id for r in interaction.user.roles}
    return bool(user_role_ids.intersection(allowed_role_ids))