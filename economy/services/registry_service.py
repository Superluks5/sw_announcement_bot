"""
Guild registry service.
------------------------------------------
Manages the request -> approve/deny flow for communities wanting to use the
shared bot's dashboard. The bot uses this registry to discover approved
servers for command registration.
"""

from economy.db import SessionLocal
from economy.models import GuildRegistry


def request_access(guild_id: int, guild_name: str, owner_discord_id: int, owner_discord_name: str, note: str = None) -> GuildRegistry:
    with SessionLocal() as session:
        existing = session.query(GuildRegistry).filter_by(guild_id=guild_id).one_or_none()
        if existing:
            # Re-requesting after a denial, or updating the note - don't create duplicates
            existing.owner_discord_id = owner_discord_id
            existing.owner_discord_name = owner_discord_name
            existing.note = note
            if existing.status == "denied":
                existing.status = "pending"
                existing.decided_at = None
                existing.decided_by = None
            session.commit()
            session.refresh(existing)
            return existing

        entry = GuildRegistry(
            guild_id=guild_id, guild_name=guild_name, owner_discord_id=owner_discord_id,
            owner_discord_name=owner_discord_name, note=note, status="pending",
        )
        session.add(entry)
        session.commit()
        session.refresh(entry)
        return entry


def get_request_for_guild(guild_id: int) -> GuildRegistry | None:
    with SessionLocal() as session:
        return session.query(GuildRegistry).filter_by(guild_id=guild_id).one_or_none()


def get_approved_guilds_for_owner(owner_discord_id: int) -> list[GuildRegistry]:
    with SessionLocal() as session:
        return session.query(GuildRegistry).filter_by(owner_discord_id=owner_discord_id, status="approved").all()


def list_pending() -> list[GuildRegistry]:
    with SessionLocal() as session:
        return session.query(GuildRegistry).filter_by(status="pending").order_by(GuildRegistry.requested_at).all()


def list_all() -> list[GuildRegistry]:
    with SessionLocal() as session:
        return session.query(GuildRegistry).order_by(GuildRegistry.requested_at.desc()).all()


def decide(registry_id: int, approve: bool, decided_by: int) -> GuildRegistry | None:
    from datetime import datetime, timezone
    with SessionLocal() as session:
        entry = session.get(GuildRegistry, registry_id)
        if entry is None:
            return None
        entry.status = "approved" if approve else "denied"
        entry.decided_at = datetime.now(timezone.utc)
        entry.decided_by = decided_by
        session.commit()
        session.refresh(entry)
        return entry


def auto_register_pending(guild_id: int, guild_name: str, owner_discord_id: int, owner_discord_name: str) -> GuildRegistry:
    """Called by the bot itself (on_guild_join) when someone invites it to
    a server that never went through the web request flow. Creates the
    same kind of pending entry the web form would, so the super-admin
    review page treats both paths identically."""
    with SessionLocal() as session:
        existing = session.query(GuildRegistry).filter_by(guild_id=guild_id).one_or_none()
        if existing:
            return existing  # already known (pending/approved/denied) - don't overwrite a decision

        entry = GuildRegistry(
            guild_id=guild_id, guild_name=guild_name, owner_discord_id=owner_discord_id,
            owner_discord_name=owner_discord_name, status="pending", note="Auto-created: bot was invited directly",
        )
        session.add(entry)
        session.commit()
        session.refresh(entry)
        return entry


def set_bot_enabled(registry_id: int, enabled: bool):
    with SessionLocal() as session:
        entry = session.get(GuildRegistry, registry_id)
        if entry:
            entry.bot_enabled = enabled
            session.commit()


def remove(registry_id: int) -> GuildRegistry | None:
    """Remove a server so a future invite must go through approval again."""
    with SessionLocal() as session:
        entry = session.get(GuildRegistry, registry_id)
        if entry is None:
            return None
        session.delete(entry)
        session.commit()
        return entry


def is_super_admin(user_id: str, super_admin_ids: set[str]) -> bool:
    return user_id in super_admin_ids