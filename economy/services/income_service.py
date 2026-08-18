"""
Income service - Phase 4.
------------------------------------------
/work, /crime, /rob, /daily, /weekly logic. Same principles as the rest of
the economy system: secure RNG, every payout/fine goes through
balance_service (atomic, always logged), cooldowns enforced before any
money moves.
"""

import secrets
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from economy.db import SessionLocal
from economy.models import IncomeConfig, DailyStreak
from economy.services import balance_service as bs
from economy.exceptions import EconomyError, InsufficientFundsError

DEFAULT_INCOME_CONFIGS = {
    "work": {"min_payout": 20, "max_payout": 250, "cooldown_seconds": 4 * 3600, "success_chance": 1.0, "fine_amount": 0},
    "crime": {"min_payout": 250, "max_payout": 700, "cooldown_seconds": 4 * 3600, "success_chance": 0.6, "fine_amount": 150},
    "rob": {"min_payout": 0, "max_payout": 0, "cooldown_seconds": 6 * 3600, "success_chance": 0.4, "fine_amount": 200},
}

ROB_MAX_STEAL_PERCENT = 0.20  # steal up to 20% of the target's cash on success
ROB_MIN_TARGET_BALANCE = 100  # target must have at least this much cash to be robbable

DAILY_BASE = 1000
DAILY_STREAK_BONUS_PER_DAY = 100
DAILY_MAX_STREAK_BONUS = 2000
DAILY_GRACE_HOURS = 48  # claim within 48h of the last one to keep the streak; 24-48h is the "next day" window

WEEKLY_BASE = 5000
WEEKLY_STREAK_BONUS_PER_WEEK = 500
WEEKLY_MAX_STREAK_BONUS = 5000
WEEKLY_GRACE_HOURS = 24 * 10  # within 10 days keeps the weekly streak (7-day cycle + 3-day grace)


def get_income_config(guild_id: int, command: str) -> IncomeConfig:
    defaults = DEFAULT_INCOME_CONFIGS.get(command, {"min_payout": 20, "max_payout": 100, "cooldown_seconds": 3600, "success_chance": 1.0, "fine_amount": 0})
    with SessionLocal() as session:
        stmt = sqlite_insert(IncomeConfig).values(guild_id=guild_id, command=command, **defaults).on_conflict_do_nothing(
            index_elements=["guild_id", "command"]
        )
        session.execute(stmt)
        session.commit()
        return session.query(IncomeConfig).filter_by(guild_id=guild_id, command=command).one()


def set_income_config(guild_id: int, command: str, **kwargs):
    with SessionLocal() as session:
        config = session.query(IncomeConfig).filter_by(guild_id=guild_id, command=command).one_or_none()
        if config is None:
            defaults = DEFAULT_INCOME_CONFIGS.get(command, {})
            config = IncomeConfig(guild_id=guild_id, command=command, **defaults)
            session.add(config)
        for key, value in kwargs.items():
            setattr(config, key, value)
        session.commit()


def list_income_configs(guild_id: int) -> list[IncomeConfig]:
    for cmd in DEFAULT_INCOME_CONFIGS:
        get_income_config(guild_id, cmd)
    with SessionLocal() as session:
        return session.query(IncomeConfig).filter_by(guild_id=guild_id).order_by(IncomeConfig.command).all()


def _roll_success(chance: float) -> bool:
    """secrets-based Bernoulli trial - chance is a float 0.0-1.0."""
    return secrets.randbelow(1_000_000) < int(chance * 1_000_000)


def _random_payout(min_payout: int, max_payout: int) -> int:
    if max_payout <= min_payout:
        return min_payout
    return min_payout + secrets.randbelow(max_payout - min_payout + 1)


@dataclass
class WorkResult:
    payout: int
    new_balance: int


def do_work(guild_id: int, user_id: int) -> WorkResult:
    config = get_income_config(guild_id, "work")
    remaining = bs.check_cooldown(guild_id, user_id, "work")
    if remaining:
        raise EconomyError(f"You're on cooldown. Try again in {_format_duration(remaining)}.")

    bs.set_cooldown(guild_id, user_id, "work", config.cooldown_seconds)
    payout = _random_payout(config.min_payout, config.max_payout)
    result = bs.add_cash(guild_id, user_id, payout, command="work", txn_type="income_work")
    return WorkResult(payout=payout, new_balance=result["cash"])


@dataclass
class CrimeResult:
    success: bool
    amount: int  # payout if success, fine if failure
    new_balance: int


def do_crime(guild_id: int, user_id: int) -> CrimeResult:
    config = get_income_config(guild_id, "crime")
    remaining = bs.check_cooldown(guild_id, user_id, "crime")
    if remaining:
        raise EconomyError(f"You're on cooldown. Try again in {_format_duration(remaining)}.")

    bs.set_cooldown(guild_id, user_id, "crime", config.cooldown_seconds)
    success = _roll_success(config.success_chance)

    if success:
        payout = _random_payout(config.min_payout, config.max_payout)
        result = bs.add_cash(guild_id, user_id, payout, command="crime", txn_type="income_crime")
        return CrimeResult(success=True, amount=payout, new_balance=result["cash"])
    else:
        try:
            result = bs.remove_cash(guild_id, user_id, config.fine_amount, command="crime", txn_type="income_crime_fine")
            new_balance = result["cash"]
        except InsufficientFundsError:
            # Can't fine them below zero - just take what they have via set_cash(0) semantics
            bal = bs.get_balance(guild_id, user_id)
            if bal["cash"] > 0:
                bs.remove_cash(guild_id, user_id, bal["cash"], command="crime", txn_type="income_crime_fine")
            new_balance = 0
        return CrimeResult(success=False, amount=config.fine_amount, new_balance=new_balance)


@dataclass
class RobResult:
    success: bool
    amount: int
    robber_new_balance: int


def do_rob(guild_id: int, robber_id: int, target_id: int) -> RobResult:
    if robber_id == target_id:
        raise EconomyError("You can't rob yourself.")

    config = get_income_config(guild_id, "rob")
    remaining = bs.check_cooldown(guild_id, robber_id, "rob")
    if remaining:
        raise EconomyError(f"You're on cooldown. Try again in {_format_duration(remaining)}.")

    target_balance = bs.get_balance(guild_id, target_id)
    if target_balance["cash"] < ROB_MIN_TARGET_BALANCE:
        raise EconomyError(f"That person doesn't have enough cash on hand to be worth robbing (needs at least {ROB_MIN_TARGET_BALANCE}).")

    bs.set_cooldown(guild_id, robber_id, "rob", config.cooldown_seconds)
    success = _roll_success(config.success_chance)

    if success:
        steal_amount = max(1, round(target_balance["cash"] * ROB_MAX_STEAL_PERCENT * (secrets.randbelow(100) / 100)))
        steal_amount = min(steal_amount, target_balance["cash"])
        try:
            result = bs.transfer(guild_id, target_id, robber_id, steal_amount, reason="robbed", command="rob")
            return RobResult(success=True, amount=steal_amount, robber_new_balance=result["receiver_cash"])
        except EconomyError:
            # Target's balance changed between our check and the transfer (race) - fail safe, no money moves
            raise EconomyError("The robbery fell through - try again.")
    else:
        try:
            result = bs.remove_cash(guild_id, robber_id, config.fine_amount, command="rob", txn_type="income_rob_fine")
            new_balance = result["cash"]
        except InsufficientFundsError:
            bal = bs.get_balance(guild_id, robber_id)
            if bal["cash"] > 0:
                bs.remove_cash(guild_id, robber_id, bal["cash"], command="rob", txn_type="income_rob_fine")
            new_balance = 0
        return RobResult(success=False, amount=config.fine_amount, robber_new_balance=new_balance)


# ---------- daily / weekly with streaks ----------

@dataclass
class StreakResult:
    payout: int
    streak: int
    new_balance: int
    streak_reset: bool


def _claim_streak(guild_id: int, user_id: int, command: str, base: int, bonus_per_period: int, max_bonus: int, grace_hours: int) -> StreakResult:
    now = datetime.now(timezone.utc)

    with SessionLocal() as session:
        row = session.query(DailyStreak).filter_by(guild_id=guild_id, user_id=user_id, command=command).one_or_none()
        if row is None:
            row = DailyStreak(guild_id=guild_id, user_id=user_id, command=command, streak=0, last_claimed_at=None)
            session.add(row)
            session.commit()
            session.refresh(row)

        if row.last_claimed_at is not None:
            last = row.last_claimed_at if row.last_claimed_at.tzinfo else row.last_claimed_at.replace(tzinfo=timezone.utc)
            hours_since = (now - last).total_seconds() / 3600
            min_gap_hours = 20 if command == "daily" else 24 * 6  # can't claim again same-day/same-week
            if hours_since < min_gap_hours:
                remaining = timedelta(hours=min_gap_hours - hours_since)
                raise EconomyError(f"Already claimed. Try again in {_format_duration(remaining)}.")

            streak_reset = hours_since > grace_hours
        else:
            streak_reset = True

        new_streak = 1 if streak_reset else row.streak + 1
        row.streak = new_streak
        row.last_claimed_at = now
        session.commit()

    bonus = min(bonus_per_period * (new_streak - 1), max_bonus)
    payout = base + bonus
    result = bs.add_cash(guild_id, user_id, payout, command=command, txn_type=f"income_{command}")
    return StreakResult(payout=payout, streak=new_streak, new_balance=result["cash"], streak_reset=streak_reset)


def do_daily(guild_id: int, user_id: int) -> StreakResult:
    return _claim_streak(guild_id, user_id, "daily", DAILY_BASE, DAILY_STREAK_BONUS_PER_DAY, DAILY_MAX_STREAK_BONUS, DAILY_GRACE_HOURS)


def do_weekly(guild_id: int, user_id: int) -> StreakResult:
    return _claim_streak(guild_id, user_id, "weekly", WEEKLY_BASE, WEEKLY_STREAK_BONUS_PER_WEEK, WEEKLY_MAX_STREAK_BONUS, WEEKLY_GRACE_HOURS)


def _format_duration(td: timedelta) -> str:
    total_seconds = int(td.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


# ---------- chat money ----------

def get_chat_money_config(guild_id: int):
    from economy.models import ChatMoneyConfig
    with SessionLocal() as session:
        stmt = sqlite_insert(ChatMoneyConfig).values(guild_id=guild_id).on_conflict_do_nothing(
            index_elements=["guild_id"]
        )
        session.execute(stmt)
        session.commit()
        return session.get(ChatMoneyConfig, guild_id)


def set_chat_money_config(guild_id: int, **kwargs):
    from economy.models import ChatMoneyConfig
    with SessionLocal() as session:
        config = session.get(ChatMoneyConfig, guild_id)
        if config is None:
            config = ChatMoneyConfig(guild_id=guild_id)
            session.add(config)
        for key, value in kwargs.items():
            setattr(config, key, value)
        session.commit()


def maybe_grant_chat_money(guild_id: int, user_id: int, channel_id: int, role_ids: list[int]) -> int | None:
    """Called from on_message. Returns the amount granted, or None if
    nothing was granted (disabled, on cooldown, excluded channel/role)."""
    config = get_chat_money_config(guild_id)
    if not config.enabled:
        return None

    excluded_channels = {c for c in config.excluded_channels.split(",") if c}
    if str(channel_id) in excluded_channels:
        return None

    excluded_roles = {r for r in config.excluded_roles.split(",") if r}
    if excluded_roles.intersection(str(r) for r in role_ids):
        return None

    remaining = bs.check_cooldown(guild_id, user_id, "chat_money")
    if remaining:
        return None

    bs.set_cooldown(guild_id, user_id, "chat_money", config.cooldown_seconds)
    amount = _random_payout(config.min_amount, config.max_amount)
    bs.add_cash(guild_id, user_id, amount, command="chat_money", txn_type="income_chat")
    return amount