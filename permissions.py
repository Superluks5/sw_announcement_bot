"""
Command permissions - edit permissions_config.json to control who can use
each command. This .py file holds the shared logic (tracked in git and
identical everywhere); the actual role IDs live in a per-server
permissions_config.json under guild_data/<guild_id>/, so two different
communities using the shared bot never see or affect each other's rules.

Since Discord's own permission menu (Server Settings -> Integrations) can
only restrict a whole command GROUP at once (e.g. all of /task together,
not /task add separately from /task show), this handles it in code
instead - down to the individual subcommand level.

HOW TO USE:
Open (or create) guild_data/<guild_id>/permissions_config.json. The key is
the command's "qualified name" - for a plain command it's just the name
(e.g. "duel"), for a subcommand it's "group subcommand" separated by a
space (e.g. "task add", "rank link"). The value is a list of Discord role
IDs (as strings) allowed to use it.

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

If a guild's permissions_config.json doesn't exist yet, it's auto-created
empty (everyone can use everything) the first time it's needed.

command_toggles.json (same per-guild folder) controls fully enabling/
disabling a command - {"command_name": false} disables it for EVERYONE
including admins, for that server only. Absent = enabled (default).

usage_data.json (same per-guild folder) is a running count of how many
times each command has been successfully used in that server - read by
the dashboard's analytics page. Purely informational, never affects
permissions.

maintenance.json (same per-guild folder) controls maintenance mode for
that one server - when enabled, blocks EVERY command for EVERYONE except
one exempt Discord user ID, overriding admin bypass entirely. Managed via
the dashboard's Maintenance page.
"""

import os
import json
import time
import discord

from guild_paths import guild_file

ADMIN_BYPASS = True


def load_config(guild_id: int) -> dict[str, list[int]]:
    path = guild_file(guild_id, "permissions_config.json")
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=2)
        return {}

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    # JSON can't hold ints this large reliably in all tools, so IDs are
    # stored as strings in the file and converted to int here for comparison.
    return {command: [int(role_id) for role_id in role_ids] for command, role_ids in raw.items()}


def load_toggles(guild_id: int) -> dict[str, bool]:
    path = guild_file(guild_id, "command_toggles.json")
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=2)
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def is_command_enabled(guild_id: int, command_name: str) -> bool:
    return load_toggles(guild_id).get(command_name, True)


def record_usage(guild_id: int, command_name: str):
    """Best-effort usage counter for the dashboard's analytics page."""
    try:
        path = guild_file(guild_id, "usage_data.json")
        data = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        entry = data.get(command_name, {"count": 0, "last_used": None, "daily": {}})
        entry.setdefault("daily", {})
        entry["count"] += 1
        entry["last_used"] = int(time.time())
        today = time.strftime("%Y-%m-%d")
        entry["daily"][today] = entry["daily"].get(today, 0) + 1
        # Keep only the last 30 days per command so the file doesn't grow forever
        if len(entry["daily"]) > 30:
            oldest_keys = sorted(entry["daily"].keys())[:-30]
            for k in oldest_keys:
                del entry["daily"][k]
        data[command_name] = entry
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️ Failed to record command usage: {e}")


def load_maintenance(guild_id: int) -> dict:
    default = {"enabled": False, "allowed_user_id": None}
    path = guild_file(guild_id, "maintenance.json")
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f, indent=2)
        return default
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    for key, value in default.items():
        data.setdefault(key, value)
    return data


def is_maintenance_blocking(guild_id: int, user_id: int) -> bool:
    """True if maintenance mode is on for this server AND this user is not
    the exempt one - this applies even to server admins, unlike every
    other check here."""
    m = load_maintenance(guild_id)
    if not m.get("enabled"):
        return False
    allowed = m.get("allowed_user_id")
    return str(user_id) != str(allowed)


def is_command_allowed(interaction: discord.Interaction) -> bool:
    if interaction.command is None:
        return True
    if interaction.guild_id is None:
        return True  # DMs - nothing to scope permissions to, let it through (existing commands all require a guild anyway)

    guild_id = interaction.guild_id
    command_name = interaction.command.qualified_name

    # Maintenance mode overrides everything else, including admin bypass -
    # that's the whole point of it.
    if isinstance(interaction.user, discord.Member) and is_maintenance_blocking(guild_id, interaction.user.id):
        return False

    is_admin = ADMIN_BYPASS and isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator

    # A fully disabled command blocks everyone, including admins - that's
    # the point of a hard disable (e.g. a broken command someone turned off).
    if not is_command_enabled(guild_id, command_name):
        return False

    if is_admin:
        record_usage(guild_id, command_name)
        return True

    command_permissions = load_config(guild_id)
    allowed_role_ids = command_permissions.get(command_name)

    if allowed_role_ids is None:
        record_usage(guild_id, command_name)
        return True  # not listed - open to everyone

    if not isinstance(interaction.user, discord.Member):
        return False

    user_role_ids = {r.id for r in interaction.user.roles}
    allowed = bool(user_role_ids.intersection(allowed_role_ids))
    if allowed:
        record_usage(guild_id, command_name)
    return allowed