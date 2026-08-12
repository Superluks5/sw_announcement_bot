"""
Command permissions - edit this file to control who can use each command.
------------------------------------------------------------------------
Since Discord's own permission menu (Server Settings -> Integrations) can
only restrict a whole command GROUP at once (e.g. all of /task together,
not /task add separately from /task show), this file handles it in code
instead - down to the individual subcommand level.

HOW TO USE:
Add an entry to COMMAND_PERMISSIONS below. The key is the command's
"qualified name" - for a plain command it's just the name (e.g. "duel"),
for a subcommand it's "group subcommand" separated by a space
(e.g. "task add", "rank link"). The value is a list of Discord role IDs
allowed to use it.

  - A command NOT listed here is open to everyone (safe default - nothing
    breaks if you forget to add a new command here).
  - A command listed with an EMPTY list [] is usable by nobody except
    admins (see ADMIN_BYPASS below).
  - Server admins (Administrator permission) can always use every command,
    regardless of what's listed here, as long as ADMIN_BYPASS is True.

To find a role's ID: enable Developer Mode in Discord (User Settings ->
Advanced), then right-click any role in Server Settings -> Roles -> Copy ID.

EXAMPLE:
    COMMAND_PERMISSIONS = {
        "promote": [123456789012345678],                # only that role
        "rank link": [123456789012345678, 987654321098765432],  # either role
        "task add": [111111111111111111],
        "task show": [],  # everyone with a role in the server usually can, but empty [] = admins only
    }
"""

import discord

ADMIN_BYPASS = True

# Fill this in with your server's real role IDs.
COMMAND_PERMISSIONS: dict[str, list[int]] = {
      "promote": [],
      "rank link": [],
      "rank unlink": [],
      "rank links": [],
      "inactivity": [],
}


def is_command_allowed(interaction: discord.Interaction) -> bool:
    if interaction.command is None:
        return True

    if ADMIN_BYPASS and isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator:
        return True

    allowed_role_ids = COMMAND_PERMISSIONS.get(interaction.command.qualified_name)
    if allowed_role_ids is None:
        return True  # not listed - open to everyone

    if not isinstance(interaction.user, discord.Member):
        return False

    user_role_ids = {r.id for r in interaction.user.roles}
    return bool(user_role_ids.intersection(allowed_role_ids))