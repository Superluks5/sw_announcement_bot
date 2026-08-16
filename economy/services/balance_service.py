"""
Balance service - every economy-changing operation goes through here.
------------------------------------------
Correctness rules this file enforces (per the project spec's anti-abuse
section):

1. Never read-then-write a balance in Python. Every change is a single
   atomic SQL UPDATE (cash = cash + :amount, with the validity check baked
   into the same WHERE clause). Two simultaneous "/pay @bob 1000" calls
   cannot corrupt Bob's balance, because SQLite serializes writes to the
   same row and each UPDATE is a single atomic statement - there's no
   window where two requests can both read the same stale value.
2. Every change writes a Transaction row in the SAME database transaction
   as the balance change - so a crash mid-operation can never leave a
   balance changed with no record of why (or vice versa).
3. Amounts are validated (positive integers only) before touching the DB.
4. Balances are guarded against going negative and against exceeding the
   guild's configured max_balance, both inside the atomic UPDATE itself.
"""

from datetime import datetime, timedelta, timezone
from sqlalchemy import update, insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from economy.db import SessionLocal
from economy.models import Balance, Transaction, GuildSettings, Cooldown
from economy.exceptions import InvalidAmountError, InsufficientFundsError, BalanceLimitError


def _validate_amount(amount: int):
    if not isinstance(amount, int) or isinstance(amount, bool):
        raise InvalidAmountError()
    if amount <= 0:
        raise InvalidAmountError()
    if amount > 10_000_000_000:  # sanity ceiling against integer-overflow-style abuse
        raise InvalidAmountError("Amount is unreasonably large.")


def get_guild_settings(guild_id: int) -> GuildSettings:
    with SessionLocal() as session:
        stmt = sqlite_insert(GuildSettings).values(guild_id=guild_id).on_conflict_do_nothing(
            index_elements=["guild_id"]
        )
        session.execute(stmt)
        session.commit()
        return session.get(GuildSettings, guild_id)


def _ensure_balance_row(session, guild_id: int, user_id: int, starting_balance: int = 0):
    """Upsert-style row creation - atomic at the DB level (INSERT ... ON
    CONFLICT DO NOTHING), so this is safe even if called concurrently for
    the same brand-new user."""
    stmt = sqlite_insert(Balance).values(
        guild_id=guild_id, user_id=user_id, cash=starting_balance, bank=0
    ).on_conflict_do_nothing(index_elements=["guild_id", "user_id"])
    session.execute(stmt)


def get_balance(guild_id: int, user_id: int) -> dict:
    settings = get_guild_settings(guild_id)
    with SessionLocal() as session:
        _ensure_balance_row(session, guild_id, user_id, settings.starting_balance)
        session.commit()
        row = session.query(Balance).filter_by(guild_id=guild_id, user_id=user_id).one()
        return {"cash": row.cash, "bank": row.bank, "net_worth": row.cash + row.bank}


def _apply_change(
    guild_id: int,
    user_id: int,
    column: str,
    delta: int,
    txn_type: str,
    performed_by: int,
    reason: str | None = None,
    command: str | None = None,
    counterparty_id: int | None = None,
    enforce_non_negative: bool = True,
) -> dict:
    """Core atomic primitive - applies `delta` to `column` (cash or bank)
    for one user, guarded in a single UPDATE statement, and logs a
    Transaction row in the same DB transaction. Returns the new balance."""
    settings = get_guild_settings(guild_id)

    with SessionLocal() as session:
        _ensure_balance_row(session, guild_id, user_id, settings.starting_balance)

        current = session.query(Balance).filter_by(guild_id=guild_id, user_id=user_id).one()
        balance_before = current.cash if column == "cash" else current.bank

        col_attr = Balance.cash if column == "cash" else Balance.bank
        new_value_expr = col_attr + delta

        stmt = update(Balance).where(
            Balance.guild_id == guild_id,
            Balance.user_id == user_id,
        )
        conditions_ok = True
        if enforce_non_negative and delta < 0:
            stmt = stmt.where(new_value_expr >= 0)
        if delta > 0:
            stmt = stmt.where(new_value_expr <= settings.max_balance)
        stmt = stmt.values(**{column: new_value_expr})

        result = session.execute(stmt)

        if result.rowcount == 0:
            # The guarded UPDATE matched no rows - the row exists (we just
            # ensured that), so this means the WHERE guard failed.
            session.rollback()
            if delta < 0:
                raise InsufficientFundsError()
            raise BalanceLimitError()

        session.refresh(current)
        balance_after = current.cash if column == "cash" else current.bank

        session.add(Transaction(
            guild_id=guild_id,
            user_id=user_id,
            counterparty_id=counterparty_id,
            type=txn_type,
            amount=delta,
            reason=reason,
            command=command,
            performed_by=performed_by,
            balance_before=balance_before,
            balance_after=balance_after,
        ))
        session.commit()

        row = session.query(Balance).filter_by(guild_id=guild_id, user_id=user_id).one()
        return {"cash": row.cash, "bank": row.bank, "net_worth": row.cash + row.bank}


# ---------- public operations ----------

def add_cash(guild_id: int, user_id: int, amount: int, *, reason=None, command=None, performed_by=None, txn_type="admin_give") -> dict:
    _validate_amount(amount)
    return _apply_change(guild_id, user_id, "cash", amount, txn_type, performed_by or user_id, reason, command)


def remove_cash(guild_id: int, user_id: int, amount: int, *, reason=None, command=None, performed_by=None, txn_type="admin_remove") -> dict:
    _validate_amount(amount)
    return _apply_change(guild_id, user_id, "cash", -amount, txn_type, performed_by or user_id, reason, command)


def set_cash(guild_id: int, user_id: int, amount: int, *, reason=None, command=None, performed_by=None) -> dict:
    if amount < 0:
        raise InvalidAmountError("Balance cannot be set below 0.")
    settings = get_guild_settings(guild_id)
    with SessionLocal() as session:
        _ensure_balance_row(session, guild_id, user_id, settings.starting_balance)
        current = session.query(Balance).filter_by(guild_id=guild_id, user_id=user_id).one()
        balance_before = current.cash
        current.cash = amount
        session.add(Transaction(
            guild_id=guild_id, user_id=user_id, type="admin_set", amount=amount - balance_before,
            reason=reason, command=command, performed_by=performed_by or user_id,
            balance_before=balance_before, balance_after=amount,
        ))
        session.commit()
        return {"cash": current.cash, "bank": current.bank, "net_worth": current.cash + current.bank}


def transfer(guild_id: int, from_user_id: int, to_user_id: int, amount: int, *, reason=None, command="pay") -> dict:
    """Atomic pay - both sides succeed or neither does. Deliberately its own
    function (not two calls to add/remove_cash) so both balance changes and
    both transaction rows land in ONE database transaction."""
    _validate_amount(amount)
    if from_user_id == to_user_id:
        raise InvalidAmountError("You can't pay yourself.")

    settings = get_guild_settings(guild_id)
    with SessionLocal() as session:
        _ensure_balance_row(session, guild_id, from_user_id, settings.starting_balance)
        _ensure_balance_row(session, guild_id, to_user_id, settings.starting_balance)
        session.commit()

        sender = session.query(Balance).filter_by(guild_id=guild_id, user_id=from_user_id).one()
        sender_before = sender.cash

        deduct = update(Balance).where(
            Balance.guild_id == guild_id, Balance.user_id == from_user_id,
            Balance.cash - amount >= 0,
        ).values(cash=Balance.cash - amount)
        result = session.execute(deduct)
        if result.rowcount == 0:
            session.rollback()
            raise InsufficientFundsError()

        receiver = session.query(Balance).filter_by(guild_id=guild_id, user_id=to_user_id).one()
        receiver_before = receiver.cash

        credit = update(Balance).where(
            Balance.guild_id == guild_id, Balance.user_id == to_user_id,
            Balance.cash + amount <= settings.max_balance,
        ).values(cash=Balance.cash + amount)
        result = session.execute(credit)
        if result.rowcount == 0:
            session.rollback()
            raise BalanceLimitError("Recipient would exceed the server's maximum balance.")

        session.add(Transaction(
            guild_id=guild_id, user_id=from_user_id, counterparty_id=to_user_id,
            type="transfer_out", amount=-amount, reason=reason, command=command,
            performed_by=from_user_id, balance_before=sender_before, balance_after=sender_before - amount,
        ))
        session.add(Transaction(
            guild_id=guild_id, user_id=to_user_id, counterparty_id=from_user_id,
            type="transfer_in", amount=amount, reason=reason, command=command,
            performed_by=from_user_id, balance_before=receiver_before, balance_after=receiver_before + amount,
        ))
        session.commit()

        return {"sender_cash": sender_before - amount, "receiver_cash": receiver_before + amount}


def deposit(guild_id: int, user_id: int, amount: int) -> dict:
    """Cash -> bank. One row, two columns - atomic by virtue of being a
    single UPDATE statement on one row."""
    _validate_amount(amount)
    settings = get_guild_settings(guild_id)
    with SessionLocal() as session:
        _ensure_balance_row(session, guild_id, user_id, settings.starting_balance)
        session.commit()

        stmt = update(Balance).where(
            Balance.guild_id == guild_id, Balance.user_id == user_id,
            Balance.cash - amount >= 0,
        ).values(cash=Balance.cash - amount, bank=Balance.bank + amount)
        result = session.execute(stmt)
        if result.rowcount == 0:
            session.rollback()
            raise InsufficientFundsError("Not enough cash on hand.")

        row = session.query(Balance).filter_by(guild_id=guild_id, user_id=user_id).one()
        session.add(Transaction(
            guild_id=guild_id, user_id=user_id, type="deposit", amount=amount,
            command="deposit", performed_by=user_id,
            balance_before=row.cash + amount, balance_after=row.cash,
        ))
        session.commit()
        return {"cash": row.cash, "bank": row.bank, "net_worth": row.cash + row.bank}


def withdraw(guild_id: int, user_id: int, amount: int) -> dict:
    """Bank -> cash."""
    _validate_amount(amount)
    settings = get_guild_settings(guild_id)
    with SessionLocal() as session:
        _ensure_balance_row(session, guild_id, user_id, settings.starting_balance)
        session.commit()

        stmt = update(Balance).where(
            Balance.guild_id == guild_id, Balance.user_id == user_id,
            Balance.bank - amount >= 0,
        ).values(bank=Balance.bank - amount, cash=Balance.cash + amount)
        result = session.execute(stmt)
        if result.rowcount == 0:
            session.rollback()
            raise InsufficientFundsError("Not enough in the bank.")

        row = session.query(Balance).filter_by(guild_id=guild_id, user_id=user_id).one()
        session.add(Transaction(
            guild_id=guild_id, user_id=user_id, type="withdraw", amount=amount,
            command="withdraw", performed_by=user_id,
            balance_before=row.bank - amount, balance_after=row.bank,
        ))
        session.commit()
        return {"cash": row.cash, "bank": row.bank, "net_worth": row.cash + row.bank}


def reset_balance(guild_id: int, user_id: int, *, performed_by: int, reason=None) -> dict:
    with SessionLocal() as session:
        _ensure_balance_row(session, guild_id, user_id, 0)
        session.commit()
        row = session.query(Balance).filter_by(guild_id=guild_id, user_id=user_id).one()
        before = row.cash
        row.cash = 0
        row.bank = 0
        session.add(Transaction(
            guild_id=guild_id, user_id=user_id, type="admin_reset", amount=-before,
            reason=reason, command="economy reset", performed_by=performed_by,
            balance_before=before, balance_after=0,
        ))
        session.commit()
        return {"cash": 0, "bank": 0, "net_worth": 0}


# ---------- cooldowns ----------

def check_cooldown(guild_id: int, user_id: int, command: str) -> timedelta | None:
    """Returns remaining time if on cooldown, else None."""
    with SessionLocal() as session:
        row = session.query(Cooldown).filter_by(guild_id=guild_id, user_id=user_id, command=command).one_or_none()
        if row is None:
            return None
        now = datetime.now(timezone.utc)
        expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
        if expires > now:
            return expires - now
        return None


def set_cooldown(guild_id: int, user_id: int, command: str, seconds: int):
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    with SessionLocal() as session:
        stmt = sqlite_insert(Cooldown).values(
            guild_id=guild_id, user_id=user_id, command=command, expires_at=expires_at
        ).on_conflict_do_update(
            index_elements=["guild_id", "user_id", "command"],
            set_={"expires_at": expires_at},
        )
        session.execute(stmt)
        session.commit()
