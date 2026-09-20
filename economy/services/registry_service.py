"""
Guild registry service.
------------------------------------------
Manages the request -> approve/deny flow for communities wanting to use the
shared bot's dashboard. The bot uses this registry to discover approved
servers for command registration.
"""

from economy.db import SessionLocal
from economy.models import GuildRegistry, OwnerAuditLog


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


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


def list_owner_audit(limit: int = 100) -> list[OwnerAuditLog]:
    with SessionLocal() as session:
        return session.query(OwnerAuditLog).order_by(OwnerAuditLog.timestamp.desc()).limit(limit).all()


def record_owner_action(
    actor_id: int,
    action: str,
    entry: GuildRegistry | None = None,
    details: str | None = None,
):
    with SessionLocal() as session:
        audit_entry = OwnerAuditLog(
            registry_id=entry.id if entry else None,
            guild_id=entry.guild_id if entry else None,
            actor_id=actor_id,
            action=action,
            details=details,
        )
        session.add(audit_entry)
        session.commit()


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
            if existing.status == "removed":
                existing.status = "pending"
                existing.bot_enabled = True
                existing.removed_at = None
            existing.guild_name = guild_name
            existing.owner_discord_id = owner_discord_id or existing.owner_discord_id
            existing.owner_discord_name = owner_discord_name or existing.owner_discord_name
            existing.bot_present = True
            existing.last_seen_at = _now()
            session.commit()
            session.refresh(existing)
            return existing

        entry = GuildRegistry(
            guild_id=guild_id, guild_name=guild_name, owner_discord_id=owner_discord_id,
            owner_discord_name=owner_discord_name, status="pending", note="Auto-created: bot was invited directly",
            bot_present=True, last_seen_at=_now(),
        )
        session.add(entry)
        session.commit()
        session.refresh(entry)
        return entry


def set_invite(registry_id: int, invite_url: str):
    with SessionLocal() as session:
        entry = session.get(GuildRegistry, registry_id)
        if entry:
            entry.invite_url = invite_url
            entry.invite_created_at = _now()
            entry.invite_error = None
            session.commit()
            session.refresh(entry)
        return entry


def set_invite_error(registry_id: int, error: str):
    with SessionLocal() as session:
        entry = session.get(GuildRegistry, registry_id)
        if entry:
            entry.invite_error = error[:300]
            session.commit()
            session.refresh(entry)
        return entry


def clear_invite(registry_id: int):
    with SessionLocal() as session:
        entry = session.get(GuildRegistry, registry_id)
        if entry:
            entry.invite_url = None
            entry.invite_created_at = None
            entry.invite_error = None
            session.commit()
            session.refresh(entry)
        return entry


def update_presence(
    registry_id: int,
    present: bool,
    guild_name: str | None = None,
    member_count: int | None = None,
    channel_count: int | None = None,
    role_count: int | None = None,
    permission_summary: str | None = None,
    snapshot: str | None = None,
):
    with SessionLocal() as session:
        entry = session.get(GuildRegistry, registry_id)
        if entry:
            entry.bot_present = present
            if guild_name:
                entry.guild_name = guild_name
            if present:
                entry.last_seen_at = _now()
            else:
                entry.last_left_at = _now()
            entry.member_count = member_count
            entry.channel_count = channel_count
            entry.role_count = role_count
            entry.permission_summary = permission_summary
            entry.snapshot = snapshot
            session.commit()
            session.refresh(entry)
        return entry


def start_review(registry_id: int, actor_id: int) -> GuildRegistry | None:
    with SessionLocal() as session:
        entry = session.get(GuildRegistry, registry_id)
        if entry is None:
            return None
        entry.status = "review"
        entry.review_started_at = _now()
        entry.reviewed_by = actor_id
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
    """Preserve the server record while marking it removed."""
    with SessionLocal() as session:
        entry = session.get(GuildRegistry, registry_id)
        if entry is None:
            return None
        entry.status = "removed"
        entry.bot_present = False
        entry.removed_at = _now()
        session.commit()
        session.refresh(entry)
        return entry


def is_super_admin(user_id: str, super_admin_ids: set[str]) -> bool:
    return user_id in super_admin_ids