"""
Per-guild data file paths.
------------------------------------------
Every JSON-backed feature (roadmap, taskboard, partners, permissions,
server config, maintenance) used to share ONE file for the whole bot
process - fine when only one server existed, actively dangerous once a
second approved community starts using the same bot: their data would
land in the exact same file as yours.

guild_file(guild_id, "roadmap_data.json") returns a path under
guild_data/<guild_id>/roadmap_data.json, creating that guild's folder on
first use. Import this from both bot-side cogs/permissions.py and the
dashboard - both need the exact same path for the exact same guild.

The whole guild_data/ folder is gitignored - it's all live, per-guild
data, same reasoning as the old top-level *_data.json files.
"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GUILD_DATA_DIR = os.path.join(BASE_DIR, "guild_data")


def guild_file(guild_id: int, filename: str) -> str:
    folder = os.path.join(GUILD_DATA_DIR, str(guild_id))
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, filename)