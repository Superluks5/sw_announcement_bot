"""
Economy database models - Phase 1.
------------------------------------------
Only the tables Phase 1 needs (balances, transactions, cooldowns, per-guild
settings). Later phases add items/shop/permissions/xp/etc. as their own
migrations - see economy/db.py's init_db(), which is additive and safe to
re-run.

Every economy table carries guild_id, even though this bot currently only
runs in one server - costs nothing now, avoids a painful migration if that
ever changes.
"""

from datetime import datetime, timezone
from sqlalchemy import String, Integer, BigInteger, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from economy.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GuildSettings(Base):
    __tablename__ = "guild_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    currency_name: Mapped[str] = mapped_column(String(50), default="Imperial Credits")
    currency_symbol: Mapped[str] = mapped_column(String(10), default="¢")
    starting_balance: Mapped[int] = mapped_column(Integer, default=500)
    max_balance: Mapped[int] = mapped_column(BigInteger, default=1_000_000_000)  # sanity ceiling, not a game-design limit


class Balance(Base):
    __tablename__ = "balances"
    __table_args__ = (UniqueConstraint("guild_id", "user_id", name="uq_balance_guild_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    cash: Mapped[int] = mapped_column(BigInteger, default=0)
    bank: Mapped[int] = mapped_column(BigInteger, default=0)


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)  # whose balance changed
    counterparty_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # other party in a transfer, if any
    type: Mapped[str] = mapped_column(String(30))  # "transfer_in" / "transfer_out" / "deposit" / "withdraw" / "admin_give" / "admin_remove" / "admin_set"
    amount: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    command: Mapped[str | None] = mapped_column(String(50), nullable=True)
    performed_by: Mapped[int] = mapped_column(BigInteger)  # who triggered this - usually == user_id, differs for admin actions
    balance_before: Mapped[int] = mapped_column(BigInteger)
    balance_after: Mapped[int] = mapped_column(BigInteger)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class PermissionRule(Base):
    """
    A single allow/deny rule. Resolution priority (highest first):
    user rule > role rule > channel rule > channel-category rule > server default.
    Within the role tier, if a user has multiple roles with conflicting
    rules, DENY always wins over ALLOW - this is deliberate (see the
    project's core security requirement: an explicit deny must never be
    overridable by some other role granting access).

    rule_type: "command" (exact match, e.g. "economy give") or "category"
    (matches every command starting with that word, e.g. "economy" matches
    "economy give", "economy remove", etc.) or the literal wildcard "*"
    stored in command_or_category (matches every economy command).

    target_type: "user" | "role" | "channel" | "channel_category"
    """
    __tablename__ = "permission_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    rule_type: Mapped[str] = mapped_column(String(20))  # "command" | "category"
    target_type: Mapped[str] = mapped_column(String(20))  # "user" | "role" | "channel" | "channel_category"
    target_id: Mapped[int] = mapped_column(BigInteger, index=True)
    command_or_category: Mapped[str] = mapped_column(String(50))  # e.g. "economy give", "economy", or "*"
    effect: Mapped[str] = mapped_column(String(10))  # "allow" | "deny"
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_by: Mapped[int] = mapped_column(BigInteger)


class RolePresetAssignment(Base):
    """Tracks which preset (if any) was last applied to a role, purely so
    the dashboard can display 'this role currently has Economy Manager' -
    the actual enforcement always goes through PermissionRule rows, this
    table is bookkeeping only."""
    __tablename__ = "role_preset_assignments"
    __table_args__ = (UniqueConstraint("guild_id", "role_id", name="uq_role_preset"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    role_id: Mapped[int] = mapped_column(BigInteger, index=True)
    preset_name: Mapped[str] = mapped_column(String(50))
    applied_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditLog(Base):
    """Every economy-admin action (money and permission changes) gets a row
    here, separate from the per-user Transaction log - this is the
    'who did what' record, not the 'whose balance changed' record."""
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    admin_id: Mapped[int] = mapped_column(BigInteger, index=True)
    action: Mapped[str] = mapped_column(String(50))
    target_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    details: Mapped[str | None] = mapped_column(String(500), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Cooldown(Base):
    __tablename__ = "cooldowns"
    __table_args__ = (UniqueConstraint("guild_id", "user_id", "command", name="uq_cooldown"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    command: Mapped[str] = mapped_column(String(50))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
