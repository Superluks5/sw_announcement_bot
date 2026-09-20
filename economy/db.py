"""
Economy database engine/session setup.
------------------------------------------
SQLite, gitignored (per-machine, like your other *_data.json files) - lives
at economy/economy.db. Chosen over Postgres deliberately: this bot runs on
a 1GB Oracle Free Tier VM, single-server-at-a-time, and SQLite's own
transaction/locking model is more than sufficient at this scale. Models are
written against plain SQLAlchemy so a future move to Postgres (if this ever
runs across many servers) is a connection-string change, not a rewrite.

WAL mode is enabled so reads (dashboard) don't block writes (bot) and vice
versa - important since the bot and dashboard are separate processes both
touching this same file.
"""

import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DB_PATH = os.path.join(os.path.dirname(__file__), "economy.db")
DB_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DB_URL, echo=False, future=True)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")  # wait up to 5s on lock contention instead of erroring immediately
    cursor.close()


class Base(DeclarativeBase):
    pass


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def _ensure_guild_registry_columns():
    """Backfill schema for older SQLite databases created before the owner panel
    added per-server bot control fields. This is intentionally lightweight and
    safe to run on every startup."""
    with engine.begin() as conn:
        table_exists = conn.exec_driver_sql(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='guild_registry'"
        ).fetchone()
        if not table_exists:
            return

        columns = [
            row[1]
            for row in conn.exec_driver_sql("PRAGMA table_info(guild_registry)").fetchall()
        ]

        if "bot_mode" not in columns:
            conn.exec_driver_sql("ALTER TABLE guild_registry ADD COLUMN bot_mode VARCHAR(20) DEFAULT 'shared'")
        if "bot_enabled" not in columns:
            conn.exec_driver_sql("ALTER TABLE guild_registry ADD COLUMN bot_enabled BOOLEAN DEFAULT 1")
        if "note" not in columns:
            conn.exec_driver_sql("ALTER TABLE guild_registry ADD COLUMN note VARCHAR(500)")
        if "decided_at" not in columns:
            conn.exec_driver_sql("ALTER TABLE guild_registry ADD COLUMN decided_at DATETIME")
        if "decided_by" not in columns:
            conn.exec_driver_sql("ALTER TABLE guild_registry ADD COLUMN decided_by BIGINT")
        if "invite_url" not in columns:
            conn.exec_driver_sql("ALTER TABLE guild_registry ADD COLUMN invite_url VARCHAR(500)")
        if "invite_created_at" not in columns:
            conn.exec_driver_sql("ALTER TABLE guild_registry ADD COLUMN invite_created_at DATETIME")


def init_db():
    """Creates all tables that don't exist yet and upgrades older SQLite
    schemas in-place. Safe to call every startup."""
    import economy.models  # noqa: F401 - ensures models are registered before create_all
    Base.metadata.create_all(engine)
    _ensure_guild_registry_columns()
