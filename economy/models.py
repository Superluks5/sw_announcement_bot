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


class GameConfig(Base):
    """Per-game, per-server settings - min/max bet, cooldown, enabled.
    Auto-created with sensible defaults the first time a game is played on
    a server (see games_service.get_game_config)."""
    __tablename__ = "game_config"
    __table_args__ = (UniqueConstraint("guild_id", "game", name="uq_game_config"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    game: Mapped[str] = mapped_column(String(30))  # "coinflip" | "dice" | "rps" | "slots" | "roulette" | "blackjack"
    min_bet: Mapped[int] = mapped_column(BigInteger, default=10)
    max_bet: Mapped[int] = mapped_column(BigInteger, default=10_000)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=3)
    enabled: Mapped[bool] = mapped_column(default=True)


class IncomeConfig(Base):
    """Per-command, per-server income settings (work/crime/rob)."""
    __tablename__ = "income_config"
    __table_args__ = (UniqueConstraint("guild_id", "command", name="uq_income_config"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    command: Mapped[str] = mapped_column(String(20))  # "work" | "crime" | "rob"
    min_payout: Mapped[int] = mapped_column(BigInteger, default=20)
    max_payout: Mapped[int] = mapped_column(BigInteger, default=250)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=14400)  # 4 hours
    success_chance: Mapped[float] = mapped_column(default=1.0)  # 1.0 = always succeeds (work); crime/rob use less
    fine_amount: Mapped[int] = mapped_column(BigInteger, default=0)  # paid on failure, for crime/rob
    enabled: Mapped[bool] = mapped_column(default=True)


class DailyStreak(Base):
    """Tracks streak state for /daily and /weekly separately from the
    generic Cooldown table, since streak logic (grace window, reset on
    miss) is different from a flat cooldown."""
    __tablename__ = "daily_streaks"
    __table_args__ = (UniqueConstraint("guild_id", "user_id", "command", name="uq_daily_streak"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    command: Mapped[str] = mapped_column(String(10))  # "daily" | "weekly"
    streak: Mapped[int] = mapped_column(Integer, default=0)
    last_claimed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ChatMoneyConfig(Base):
    """Passive per-message income settings. excluded_channels/excluded_roles
    are stored as comma-separated ID strings - simple and sufficient at
    this scale, avoids a whole extra join table for Phase 4."""
    __tablename__ = "chat_money_config"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    enabled: Mapped[bool] = mapped_column(default=False)  # opt-in, off by default
    min_amount: Mapped[int] = mapped_column(Integer, default=1)
    max_amount: Mapped[int] = mapped_column(Integer, default=5)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=60)
    excluded_channels: Mapped[str] = mapped_column(String(500), default="")
    excluded_roles: Mapped[str] = mapped_column(String(500), default="")


class RoleIncome(Base):
    """@VIP -> 500 every 12 hours, etc. Granted by a periodic background
    task (see economy/cogs/income.py), not on-demand."""
    __tablename__ = "role_income"
    __table_args__ = (UniqueConstraint("guild_id", "role_id", name="uq_role_income"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    role_id: Mapped[int] = mapped_column(BigInteger, index=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    interval_hours: Mapped[int] = mapped_column(Integer, default=12)
    enabled: Mapped[bool] = mapped_column(default=True)


class GuildRegistry(Base):
    """Platform-wide, not economy-specific - lives in the same DB for
    simplicity (one file, one session pattern, no reason to split it out).

    Tracks which Discord servers are approved to use the shared bot's
    dashboard, and who owns each one. status: 'pending' | 'approved' | 'denied'.
    bot_mode: 'shared' (free, runs on the main bot) | 'dedicated' (paid,
    their own bot token/process - Phase 2, not built yet)."""
    __tablename__ = "guild_registry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    guild_name: Mapped[str] = mapped_column(String(200))
    owner_discord_id: Mapped[int] = mapped_column(BigInteger, index=True)
    owner_discord_name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    bot_mode: Mapped[str] = mapped_column(String(20), default="shared")
    bot_enabled: Mapped[bool] = mapped_column(default=True)  # super-admin kill switch per server, independent of approval status
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decided_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    invite_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    invite_created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class OwnerAuditLog(Base):
    """Platform-wide record of actions taken in the Owner Panel."""
    __tablename__ = "owner_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    registry_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    guild_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    actor_id: Mapped[int] = mapped_column(BigInteger, index=True)
    action: Mapped[str] = mapped_column(String(50))
    details: Mapped[str | None] = mapped_column(String(500), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)